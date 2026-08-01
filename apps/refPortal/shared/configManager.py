import json
import os
import threading
from pathlib import Path


class ConfigManager:
    _config_watch_lock = threading.Lock()
    _config_watch_started = False
    _config_watch_observers = []
    _config_watch_subscribers = []
    _config_watch_logger = None

    _merged_file_config_cache = None
    _merged_config_lock = threading.Lock()

    @staticmethod
    def safe_load_json(path: Path):
        if not path.exists():
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as file:
                return json.load(file)
        except Exception:
            return {}

    @staticmethod
    def deep_merge_dict(base: dict, override: dict):
        result = dict(base or {})
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = ConfigManager.deep_merge_dict(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _load_merged_file_config(selected_env: str = None):
        """Read and merge config JSON from disk. Call only from get/reload helpers or tests."""
        config_dir = Path(os.getenv('MY_CONFIG_FOLDER', '/run/config'))
        if not config_dir.exists():
            raise FileNotFoundError(f'Config directory not found: {config_dir}')
        common_config = ConfigManager.safe_load_json(config_dir / 'config.common.json')
        common_env_name: str = common_config.get('env', {}).get('app_env', 'dev')
        effective_env: str = selected_env or os.getenv('app_env', common_env_name)
        env_config = ConfigManager.safe_load_json(config_dir / f'config.{effective_env}.json')
        return ConfigManager.deep_merge_dict(common_config, env_config)

    @classmethod
    def get_merged_file_config(cls, selected_env: str = None):
        """
        Return merged on-disk config (common + env). Loads from disk on first call only.
        Subscribers should use the `merged` argument from config change callbacks instead of this
        for reacting to file updates; use this for initial/read-only access.
        """
        with cls._merged_config_lock:
            if cls._merged_file_config_cache is None:
                cls._merged_file_config_cache = cls._load_merged_file_config(selected_env)
            return cls._merged_file_config_cache

    @classmethod
    def reload_merged_file_config(cls, selected_env: str = None):
        """
        Reload merged config from disk and update the cache. Used on config file watch events
        and when a fresh read is required. This is the only path that re-reads files after startup.
        """
        with cls._merged_config_lock:
            cls._merged_file_config_cache = cls._load_merged_file_config(selected_env)
            return cls._merged_file_config_cache

    @staticmethod
    def _env_value_to_str(value):
        if isinstance(value, bool):
            return 'True' if value else 'False'
        if isinstance(value, (list, tuple)):
            return ','.join(str(v) for v in value)
        if isinstance(value, dict):
            return json.dumps(value)
        return str(value)

    _bridged_env_keys = set()

    @classmethod
    def sync_env_to_process(cls, merged_file_config: dict = None):
        """
        Populate os.environ from the merged JSON config's 'env' section for any key not already
        set in the real process environment. Legacy code across shared/rpApi/rpGw reads
        os.getenv() directly rather than through this class, so this bridges config.common.json /
        config.{env}.json to those call sites without rewriting them. A genuine external env var
        (docker-compose service override, local `export` for debugging) always wins and is never
        overwritten; a value this bridge itself wrote on a previous call is fair game to update, so
        hot-reload (this is also called from the config file watcher) reaches those call sites too.
        """
        merged = merged_file_config if merged_file_config is not None else cls.get_merged_file_config()
        env_section = merged.get('env', {}) if isinstance(merged, dict) else {}
        for key, value in env_section.items():
            if key in os.environ and key not in cls._bridged_env_keys:
                continue
            if value is None:
                continue
            os.environ[key] = cls._env_value_to_str(value)
            cls._bridged_env_keys.add(key)

    @staticmethod
    def get_resolved_config_json_paths() -> list:
        """
        Paths to config.common.json and config.{effective_env}.json under MY_CONFIG_FOLDER,
        matching _load_merged_file_config() effective_env resolution.
        """
        config_dir = Path(os.getenv('MY_CONFIG_FOLDER', '/run/config'))
        paths = []
        if not config_dir.is_dir():
            return paths
        common_path = config_dir / 'config.common.json'
        if not common_path.is_file():
            return paths
        paths.append(common_path.resolve())
        common_config = ConfigManager.safe_load_json(common_path)
        common_env_name = common_config.get('env', {}).get('app_env', 'local')
        effective_env = os.getenv('app_env', common_env_name)
        env_file = config_dir / f'config.{effective_env}.json'
        if env_file.is_file():
            paths.append(env_file.resolve())
        return paths

    @staticmethod
    def _debounce_config_callback(on_change, debounce_seconds: float):
        timer_holder = {'t': None}
        lock = threading.Lock()

        def wrapped(file_path, fname=None):
            def fire():
                on_change(file_path, fname)

            with lock:
                if timer_holder['t'] is not None:
                    timer_holder['t'].cancel()
                timer_holder['t'] = threading.Timer(debounce_seconds, fire)
                timer_holder['t'].daemon = True
                timer_holder['t'].start()

        return wrapped

    @classmethod
    def _notify_config_watch_subscribers(cls, file_path, fname=None):
        try:
            merged = cls.reload_merged_file_config()
        except FileNotFoundError as ex:
            log = cls._config_watch_logger
            if log is not None:
                log.warning(f'Config reload skipped after file change: {ex}')
            return
        cls.sync_env_to_process(merged)
        for cb in list(cls._config_watch_subscribers):
            try:
                cb(merged, file_path, fname)
            except Exception as ex:
                log = cls._config_watch_logger
                if log is not None:
                    log.error('Config file change subscriber raised', ex)
                else:
                    raise

    @classmethod
    def _ensure_config_file_watcher(cls, debounce_seconds: float):
        from shared.fileWatcher import watchFileChange

        paths = cls.get_resolved_config_json_paths()
        if not paths:
            log = cls._config_watch_logger
            if log is not None:
                log.warning(
                    f'No config JSON files to watch under MY_CONFIG_FOLDER '
                    f'({os.getenv("MY_CONFIG_FOLDER", "/run/config")}); '
                    'config file watcher not started'
                )
            return
        debounced = cls._debounce_config_callback(
            cls._notify_config_watch_subscribers,
            debounce_seconds,
        )
        for p in paths:
            try:
                obs = watchFileChange(str(p), debounced)
                cls._config_watch_observers.append(obs)
            except Exception as ex:
                log = cls._config_watch_logger
                if log is not None:
                    log.error(f'Failed to watch config file {p}', ex)
                else:
                    raise
        log = cls._config_watch_logger
        if log is not None:
            log.info(f'ConfigManager watching config files paths={paths}')

    @classmethod
    def subscribe_config_changes(cls, callback, debounce_seconds=0.75, logger=None):
        """
        Register for merged config JSON changes. ConfigManager reloads merged JSON from disk
        (reload_merged_file_config) after debounce, then notifies callbacks with:
        callback(merged_file_config, file_path, fname).
        Subscribers must not read config files; they only apply or handle `merged_file_config`.
        Callbacks run on the watchdog/timer thread.
        """
        with cls._config_watch_lock:
            if logger is not None:
                cls._config_watch_logger = logger
            cls._config_watch_subscribers.append(callback)
            if not cls._config_watch_started:
                cls._ensure_config_file_watcher(debounce_seconds)
                cls._config_watch_started = True

    @staticmethod
    def get_env_value(name, file_env_values: dict, default=None):
        file_value = (file_env_values or {}).get(name, default)
        return os.getenv(name, file_value)

    @staticmethod
    def to_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value) == 'True'

    @staticmethod
    def to_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def get_config_value(config: dict, key: str, default=None):
        if not isinstance(config, dict):
            return default
        if key in config:
            return config.get(key)
        if key == 'app_env':
            return config.get('env', default)
        return default

    @staticmethod
    def get_config_bool(config: dict, key: str, default=False):
        value = ConfigManager.get_config_value(config, key, default)
        return ConfigManager.to_bool(value, default)

    @staticmethod
    def get_config_int(config: dict, key: str, default=0):
        value = ConfigManager.get_config_value(config, key, default)
        return ConfigManager.to_int(value, default)

    @staticmethod
    def get_config_float(config: dict, key: str, default=0.0):
        value = ConfigManager.get_config_value(config, key, default)
        return ConfigManager.to_float(value, default)

