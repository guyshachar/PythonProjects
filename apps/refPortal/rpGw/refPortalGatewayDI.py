import logging
from datetime import datetime, timedelta
import os
import sys
import json
from pathlib import Path
import socket
import asyncio
import uuid
import requests
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Import the dependency injection container
from shared.appContainer import AppContainer
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.logger import Logger
from shared.configManager import ConfigManager
from shared.fileWatcher import watchFileChange
import shared.configurationDI as configDI
from shared import playwright_shared_browser

class RefPortalServiceDI():
    """
    RefPortalService using dependency injection with shared.appContainer
    """
    
    def __init__(self, container: AppContainer = None):
        """
        Initialize the service with dependency injection.
        
        Args:
            container: Optional AppContainer instance. If not provided, creates a new one.
        """
        # Create container if not provided
        if container is None:
            self.container = AppContainer()
            self._configure_container()
        else:
            self.container = container
            
        # Get dependencies from container
        self.logger = self.container.logger()
        self.cacheService = self.container.cache_service()
        self.messagingService = self.container.messaging_service()
        self.handleUsers = self.container.handle_users()
        self.handleTournaments = self.container.handle_tournaments()
        self.handleRefereeData = self.container.handle_referee_data()
        self.refereeProcessService = self.container.referee_process_service()
        self.orgServiceFactory = self.container.orgServiceFactory()
        configDI.register_config_container(self.container)
        self.config: dict = self.container.config()
        self._sync_service_settings_from_config()
        self.cronjob_task_configs = self._load_cronjob_configs()
        self.logger.debug(f'cronjob_task_configs: {self.cronjob_task_configs}')
        self.cronjob_function_handlers = self._get_cronjob_function_handlers()
        self._cronjob_last_run_at = {}
        self._cronjob_started_at = helpers.localNow()
        self._cronjob_scheduler_task = None
        self.cronjob_run_logger = self._create_cronjob_run_logger()
        
        # Initialize startup message
        self.hostname = socket.gethostname()
        self.open_text = f'Ref Portal Service DI {jsonHelper.datetime_to_str(helpers.localNow())} build#{ConfigManager.get_config_value(self.config, "BUILD_DATE", "")} host={self.hostname}'
        self.logger.info(self.open_text)
        
        # File watchers (referees); merged JSON reload + flat DI is configurationDI.subscribe_merged_config_changes
        self.referee_file_watch_observer = None

        self.logger.info(f'RefPortalServiceDI starts with dependency injection...')

    def _sync_service_settings_from_config(self):
        self.app_replicas = ConfigManager.get_config_int(self.config, 'APP_REPLICAS', 1)
        self.replica_slot = ConfigManager.get_config_int(self.config, 'REPLICA_SLOT', 1)
        self.main_instance = ConfigManager.get_config_bool(self.config, 'mainInstance', False) or self.replica_slot == 1
        self.env = ConfigManager.get_config_value(self.config, 'app_env', ConfigManager.get_config_value(self.config, 'env'))
        self.generate_reports = ConfigManager.get_config_bool(self.config, 'generateReports', False)
        self.load_interval = ConfigManager.get_config_int(self.config, 'loadInterval', 10000)
        self.sw_level = ConfigManager.get_config_value(self.config, 'swLevel', 'debug')
        self.referees_per_run = ConfigManager.get_config_int(self.config, 'refereesPerRun', 10)
        self.enable_cronjobs = ConfigManager.get_config_bool(self.config, 'enableCronjobs', False)
        self.cronjob_poll_interval_seconds = ConfigManager.get_config_float(self.config, 'cronjobPollIntervalSeconds', 60.0)
        # Gateway: one shared Chromium by default (overridable via singlePlaywrightBrowser in merged config).
        self.refereeProcessService.single_playwright_browser = ConfigManager.get_config_bool(
            self.config, 'singlePlaywrightBrowser', True
        )

    def _create_cronjob_run_logger(self):
        cronjobLogger = Logger(
            loggerName=f'{self.__class__.__name__}_cronjobs_{os.getpid()}',
            log2Console=True,
            log2File=True,
            sendMessage=None,
            config=self.config
        )
        return cronjobLogger

    def _log_cronjob_run(self, task_id, status, **extra):
        payload = {
            'timestamp': helpers.localNow().isoformat(),
            'taskId': task_id,
            'status': status,
            'hostname': self.hostname,
            **extra
        }
        self.cronjob_run_logger.info(json.dumps(payload, ensure_ascii=False, default=str))

    def _default_cronjob_configs(self):
        """Job id is the key (matches merged JSON); values have no `id` field."""
        return {
            "refresh_leagues_tables": {
                "action": "refresh_leagues_tables",
                "type": "function",
                "function":  "refreshLeaguesTables",
                "enabled": True,
                "intervalHours": 12,
                "instanceTarget": "mainOnly",
                "runOnStartup": False
            },
            "refresh_tournament_games": {
                "action": "refresh_tournament_games",
                "type": "function",
                "function": "refreshTournamentGames",
                "enabled": True,
                "intervalHours": 6,
                "instanceTarget": "mainOnly",
                "runOnStartup": False
            }
        }

    def _load_cronjob_configs(self):
        """Cronjobs as dict keyed by job id (flat self.config / configurationDI)."""
        defaults = self._default_cronjob_configs()
        parsed = ConfigManager.get_config_value(self.config, 'cronjobs')
        if not parsed:
            return defaults
        if not isinstance(parsed, dict):
            self.logger.warning('cronjobs must be a dict; using defaults.')
            return defaults
        return ConfigManager.deep_merge_dict(defaults, parsed)

    def _get_cronjob_function_handlers(self):
        return {
            'refreshLeaguesTables': self._run_refresh_leagues_tables_cronjob,
            'refreshTournamentGames': self._run_refresh_tournament_games_cronjob,
            'startRefereeProcessing': self._run_start_referee_processing_cronjob
        }

    def _apply_cronjob_task_configs(self, new_configs, reason='manual'):
        existing_task_ids = set(new_configs.keys())
        self._cronjob_last_run_at = {
            task_id: last_run
            for task_id, last_run in self._cronjob_last_run_at.items()
            if task_id in existing_task_ids
        }
        self._cronjob_started_at = helpers.localNow()
        self.cronjob_task_configs = new_configs
        self.logger.info(
            f'Cronjobs config reloaded reason={reason} jobs={len(new_configs)}'
        )
        self._log_cronjob_run(
            task_id='cronjob_config',
            status='reloaded',
            reason=reason,
            jobsCount=len(new_configs)
        )

    def _reload_cronjob_configs(self, reason='manual'):
        self._apply_cronjob_task_configs(self._load_cronjob_configs(), reason=reason)

    def _propagate_config_to_injected_services(self):
        """Point all injected components at the current flat self.config dict."""
        cfg = self.config
        if hasattr(self.logger, 'config'):
            self.logger.config = cfg
        if hasattr(self.messagingService, 'config'):
            self.messagingService.config = cfg
        if hasattr(self.cronjob_run_logger, 'config'):
            self.cronjob_run_logger.config = cfg
        rps = getattr(self, 'refereeProcessService', None)
        if rps is not None and hasattr(rps, 'config'):
            rps.config = cfg

    def _after_flat_config_reloaded(self, new_di, file_path=None, fname=None):
        """Runs after configurationDI rebuilt flat config + container; only service-layer state."""
        self.logger.debug(f'Flat config updated from watcher path={file_path} file={fname}')
        try:
            self.config = new_di
            self._sync_service_settings_from_config()
            self._propagate_config_to_injected_services()
            new_configs = self._load_cronjob_configs()
            self._apply_cronjob_task_configs(new_configs, reason='config_file_watch')
            self.logger.info(
                f'Applied service config after DI reload cronjobs={len(new_configs)} '
                f'enableCronjobs={self.enable_cronjobs} pollInterval={self.cronjob_poll_interval_seconds}s'
            )
        except Exception as ex:
            self.logger.error('Config apply after DI reload failed', ex)

    def _setup_config_file_watcher(self):
        configDI.subscribe_merged_config_changes(
            after_reload=self._after_flat_config_reloaded,
            debounce_seconds=0.75,
            logger=self.logger,
        )

    def _get_cronjob_interval_seconds(self, task_config):
        if task_config.get('intervalSeconds') is not None:
            return int(task_config.get('intervalSeconds'))
        if task_config.get('intervalMinutes') is not None:
            return int(task_config.get('intervalMinutes')) * 60
        if task_config.get('intervalHours') is not None:
            return int(task_config.get('intervalHours')) * 60 * 60
        return 0

    def _cronjob_should_run_on_this_instance(self, task_config):
        """
        instanceTarget: mainOnly | all | odd | even
        Legacy: mainInstanceOnly true -> mainOnly, false -> all (used when instanceTarget is absent).
        Default when neither is set: all.
        """
        target = task_config.get('instanceTarget')
        if target is None and task_config.get('mainInstanceOnly') is not None:
            target = 'mainOnly' if task_config.get('mainInstanceOnly') else 'all'
        if target is None:
            target = 'all'
        if not isinstance(target, str):
            target = str(target)
        target = target.strip().lower()
        if target == 'all':
            return True
        if target == 'mainonly':
            return self.main_instance
        if target == 'odd':
            return (self.replica_slot % 2) == 1
        if target == 'even':
            return (self.replica_slot % 2) == 0 or self.app_replicas == 1
        self.logger.warning(
            f'Cronjob {task_config.get("id")} has unknown instanceTarget={target!r}, treating as all'
        )
        return True

    def _is_cronjob_due(self, task_config):
        task_id = task_config.get('id')
        if not task_id:
            return False
        if not task_config.get('enabled', True):
            return False
        if not self._cronjob_should_run_on_this_instance(task_config):
            return False

        interval_seconds = self._get_cronjob_interval_seconds(task_config)
        if interval_seconds <= 0:
            self.logger.warning(f'Cronjob {task_id} has invalid interval and will be skipped')
            return False

        now = helpers.localNow()
        last_run_at = self._cronjob_last_run_at.get(task_id)
        if last_run_at is None:
            if task_config.get('runOnStartup', False):
                return True
            return (now - self._cronjob_started_at).total_seconds() >= interval_seconds
        return (now - last_run_at).total_seconds() >= interval_seconds

    def _schedule_due_cronjobs(self):
        for task_id, task_cfg in self.cronjob_task_configs.items():
            task_config = {**task_cfg, 'id': task_id}
            if not self._is_cronjob_due(task_config):
                continue

            self._cronjob_last_run_at[task_id] = helpers.localNow()
            self.logger.info(f'Scheduling cronjob={task_id}')
            self._log_cronjob_run(task_id=task_id, status='scheduled', taskConfig=task_config)
            asyncio.create_task(self._run_cronjob_task(task_config=task_config))

    async def _cronjob_scheduler_loop(self):
        self.logger.info(
            f'Cronjob scheduler loop started with poll interval={self.cronjob_poll_interval_seconds}s '
            f'jobs={len(self.cronjob_task_configs)}'
        )
        while True:
            try:
                self._schedule_due_cronjobs()
                await asyncio.sleep(self.cronjob_poll_interval_seconds)
            except asyncio.CancelledError:
                self.logger.info('Cronjob scheduler loop cancelled')
                break
            except Exception as ex:
                self.logger.error('Cronjob scheduler loop error', ex)
                await asyncio.sleep(self.cronjob_poll_interval_seconds)

    def _get_cronjob_tenant_keys(self, task_config):
        configured_tenant_keys = task_config.get('tenantKeys')
        if configured_tenant_keys and isinstance(configured_tenant_keys, list):
            return configured_tenant_keys

        tenants = self.cacheService.getTenants(forceReload=True) or {}
        tenant_keys = list(tenants.keys())

        filtered_tenant_keys = ConfigManager.get_config_value(self.config, 'filteredTenantKeys', '')
        if filtered_tenant_keys:
            allowed_tenants = filtered_tenant_keys.split(',')
            tenant_keys = [tenant_key for tenant_key in tenant_keys if tenant_key in allowed_tenants]
        return tenant_keys

    async def _run_refresh_leagues_tables_cronjob(self, task_config):
        tenant_keys = self._get_cronjob_tenant_keys(task_config)
        tournament_name = task_config.get('tournamentName')
        self.logger.info(
            f'Cronjob refresh_leagues_tables started tenants={tenant_keys} '
            f'tournamentName={tournament_name}'
        )

        summary = {}
        for tenant_key in tenant_keys:
            try:
                org_service = self.orgServiceFactory.get_org_service_by_tenant(tenantKey=tenant_key)
                (result, message) = await org_service.refreshLeaguesTables(tenantKey=tenant_key, tournamentName=tournament_name)
                summary[tenant_key] = {
                    'result': result,
                    'message': message
                }
            except Exception as ex:
                self.logger.error(
                    f'Cronjob refresh_leagues_tables failed for tenant={tenant_key} '
                    f'tournamentName={tournament_name}',
                    ex
                )
                self._log_cronjob_run(
                    task_id='refresh_leagues_tables',
                    status='tenant_failed',
                    tenantKey=tenant_key,
                    tournamentName=tournament_name,
                    error=str(ex)
                )

        self.logger.info('Cronjob refresh_leagues_tables completed')
        return summary

    async def _run_refresh_tournament_games_cronjob(self, task_config):
        summary = {}
        if (task_config.get('tenantKeys')):
            tenant_keys = task_config.get('tenantKeys')
        else:
            tenant_keys = self._get_cronjob_tenant_keys(task_config)
        tournament_name = task_config.get('tournamentName')
        round_val = task_config.get('round')
        fixture_val = task_config.get('fixture')
        from_fixture_val = task_config.get('fromFixture')
        fetch_games_urls = task_config.get('fetchGamesUrls', False)
        fetch_games_details = task_config.get('fetchGamesDetails', False)
        fetch_referees = task_config.get('fetchReferees', False)
        tournament_types = task_config.get('tournamentTypes', ['league'])
        instance = task_config.get('instance', 0)
        if isinstance(tournament_types, str):
            tournament_types = [t.strip() for t in tournament_types.split(',') if t.strip()] or ['league']
        task_id = task_config.get('id') or 'refresh_tournament_games'
        self.logger.info(
            f'Cronjob {task_id} started tenants={tenant_keys} tournamentName={tournament_name} '
            f'round={round_val} fixture={fixture_val} tournamentTypes={tournament_types}'
        )

        for tenant_key in tenant_keys:
            try:
                (result, message) = await self.handleTournaments.refreshTournamentGames(
                    tenantKey=tenant_key,
                    tournamentName=tournament_name,
                    round1=round_val,
                    fixture=fixture_val,
                    fromFixture=from_fixture_val,
                    fetchGamesUrls=fetch_games_urls,
                    fetchGamesDetails=fetch_games_details,
                    fetchReferees=fetch_referees,
                    tournamentTypes=tournament_types,
                    instance=instance
                )
                summary[tenant_key] = {
                    'result': result,
                    'message': message
                }
            except Exception as ex:
                self.logger.error(
                    f'Cronjob {task_id} failed for tenant={tenant_key} tournamentName={tournament_name}',
                    ex
                )
                self._log_cronjob_run(
                    task_id=task_id,
                    status='tenant_failed',
                    tenantKey=tenant_key,
                    tournamentName=tournament_name,
                    error=str(ex)
                )

        self.logger.info(f'Cronjob {task_id} completed, summary={summary}')
        return summary

    def _resolve_cronjob_api_url(self, endpoint):
        if endpoint.startswith('http://') or endpoint.startswith('https://'):
            return endpoint

        api_base = str(ConfigManager.get_config_value(self.config, 'apiServiceUrlBase', '')).strip()
        if not api_base:
            return endpoint
        if endpoint.startswith('/'):
            return f'{api_base.rstrip("/")}{endpoint}'
        return f'{api_base.rstrip("/")}/{endpoint}'

    async def _run_api_cronjob(self, task_config):
        endpoint = task_config.get('endpoint') or task_config.get('url')
        if not endpoint:
            self.logger.warning(f'Cronjob {task_config.get("id")} missing endpoint for type=api')
            self._log_cronjob_run(
                task_id=task_config.get('id'),
                status='failed',
                error='missing endpoint for api cronjob'
            )
            return

        url = self._resolve_cronjob_api_url(endpoint=endpoint)
        method = str(task_config.get('method', 'GET')).upper()
        timeout_seconds = int(task_config.get('timeoutSeconds', 10))
        payload = task_config.get('payload')
        self.logger.info(
            f'Cronjob api request started id={task_config.get("id")} method={method} url={url} '
            f'timeoutSeconds={timeout_seconds}'
        )

        try:
            request_kwargs = {'timeout': timeout_seconds}
            if payload is not None and method in ['POST', 'PUT', 'PATCH', 'DELETE']:
                request_kwargs['json'] = payload

            response = requests.request(method, url, **request_kwargs)
            self._log_cronjob_run(
                task_id=task_config.get('id'),
                status='completed',
                url=url,
                method=method,
                httpStatusCode=response.status_code
            )
            if response.status_code >= 400:
                self.logger.warning(
                    f'Cronjob api request returned status={response.status_code} id={task_config.get("id")} '
                    f'method={method} url={url}'
                )
            else:
                self.logger.info(
                    f'Cronjob api request completed status={response.status_code} id={task_config.get("id")} '
                    f'method={method} url={url}'
                )
        except Exception as ex:
            self._log_cronjob_run(
                task_id=task_config.get('id'),
                status='failed',
                url=url,
                method=method,
                error=str(ex)
            )
            self.logger.error(
                f'Cronjob api request failed id={task_config.get("id")} method={method} url={url}',
                ex
            )

    async def _run_start_referee_processing_cronjob(self, task_config):
        self.load_metadata()
        summary = await self._run_referee_processing_cycle(task_config=task_config)
        return summary

    async def _run_function_cronjob(self, task_config):
        function_name = task_config.get('function')
        handler = self.cronjob_function_handlers.get(function_name)
        if not handler:
            self.logger.warning(
                f'Cronjob {task_config.get("id")} uses unknown function={function_name}'
            )
            self._log_cronjob_run(
                task_id=task_config.get('id'),
                status='failed',
                error=f'unknown function handler: {function_name}'
            )
            return
        summary = await handler(task_config=task_config)
        return summary

    async def _run_cronjob_task(self, task_config):
        task_id = task_config.get('id')
        task_type = task_config.get('type')
        try:
            self._log_cronjob_run(task_id=task_id, status='started', type=task_type)
            if task_type == 'api':
                await self._run_api_cronjob(task_config=task_config)
            elif task_type == 'function':
                summary = await self._run_function_cronjob(task_config=task_config)
                self._log_cronjob_run(task_id=task_id, status='completed', summary=summary)
            else:
                self.logger.warning(
                    f'Unknown cronjob type={task_type} id={task_id}, skipping'
                )
                self._log_cronjob_run(
                    task_id=task_id,
                    status='skipped_unknown_type',
                    type=task_type
                )
        except Exception as ex:
            self.logger.error(f'Cronjob execution failed id={task_id}', ex)
            self._log_cronjob_run(task_id=task_id, status='failed', type=task_type, error=str(ex))
    
    def _configure_container(self):
        """
        Configure the container with environment variables.
        """
        self.container.config.from_dict(configDI.configDI)
        
        # Initialize container resources
        self.container.init_resources()

    async def start(self):
        """
        Start the service with dependency injection.
        """
        self.logger.debug('Start RefPortalServiceDI')
        self.messagingService.mqttClient.publish(
            topic=self.messagingService.mqttTopic, 
            title=f"RefPortalServiceDI Starts... host={self.hostname}", 
            payload=self.open_text
        )

        try:
            helpers.stopwatchStart('Interval processing')
            if self.enable_cronjobs:
                self._setup_config_file_watcher()
                self._cronjob_scheduler_task = asyncio.create_task(self._cronjob_scheduler_loop())
                await self._cronjob_scheduler_task
            else:
                self.logger.warning('Cronjobs are disabled; service will stay idle')
                while True:
                    await asyncio.sleep(60)

        except Exception as ex:
            self.logger.error(f'start', ex)
        
        finally:
            self.logger.debug(f'close')

            if self._cronjob_scheduler_task:
                self._cronjob_scheduler_task.cancel()
                try:
                    await self._cronjob_scheduler_task
                except asyncio.CancelledError:
                    pass

            if getattr(self.refereeProcessService, 'single_playwright_browser', False):
                await playwright_shared_browser.shutdown()
            
            # Shutdown container resources
            self.container.shutdown_resources()

    async def _run_referee_processing_cycle(self, task_config=None):
        summary = {}
        cycle_tenant_keys = None
        if task_config and isinstance(task_config.get('tenantKeys'), list):
            cycle_tenant_keys = task_config.get('tenantKeys')

        any_change = False
        helpers.stopwatchStart('Loop time')
        tenantKeys = cycle_tenant_keys or list(self.handleRefereeData.activeRefereeByMobileNos.keys())
        filtered_tenant_keys = task_config.get('tenantKeys') or ConfigManager.get_config_value(self.config, 'filteredTenantKeys', '')
        if filtered_tenant_keys:
            tenantKeys = [tenantKey for tenantKey in tenantKeys if tenantKey in filtered_tenant_keys]
        self.logger.info(f'running with tenantKeys: {tenantKeys}')

        for tenantKey in tenantKeys:
            if tenantKey not in self.handleRefereeData.activeRefereeByMobileNos:
                self.logger.warning(f'Skipping tenant without active referee data: {tenantKey}')
                continue
            activeRefereesByTenant = self.handleRefereeData.activeRefereeByMobileNos[tenantKey]
            filtered_mobile_nos = task_config.get('mobileNos') or ConfigManager.get_config_value(self.config, 'filteredMobileNos', [])
            if filtered_mobile_nos:
                mobileNos = [mobileNo for mobileNo in activeRefereesByTenant.keys() if mobileNo in filtered_mobile_nos]
                filteredActiveRefereesByTenant = {mobileNo: activeRefereesByTenant[mobileNo] for mobileNo in mobileNos}
            else:
                filteredActiveRefereesByTenant = {mobileNo: activeRefereesByTenant[mobileNo] for mobileNo in activeRefereesByTenant.keys()}
            referee_items = list(dict({mobileNo: referee for mobileNo, referee in filteredActiveRefereesByTenant.items() if referee.get('portalAllow', False) == True}).items())
            for i in range(0, len(referee_items), self.referees_per_run):
                batch_referees = dict(referee_items[i: i + self.referees_per_run])
                self.logger.info(f'Processing tenantKey={tenantKey} {len(batch_referees)} referees...')

                invocation_id = str(uuid.uuid4())
                payload = {'invocationId': invocation_id, 'refereeIds': batch_referees.keys()}
                any_change = await self.refereeProcessService.startProcessByReferees(tenantKey=tenantKey, referees=batch_referees)
                summary[tenantKey] = {
                    'result': any_change,
                    'message': 'Referee processing completed'
                }
                self.cacheService.setInvocation(tenantKey=tenantKey, invocationId=invocation_id, value=payload)

            if self.generate_reports and self.main_instance and any_change:
                await self.handleRefereeData.collectGamesSummary()

            self.logger.info(f'tenantKey={tenantKey} #referees={len(self.handleRefereeData.activeRefereeByRefId[tenantKey])}')
        helpers.stopwatchStop('Loop time', level='info')
        return summary

    def load_metadata(self, initial=False):
        """
        Load metadata using injected dependencies.
        """
        try:
            referee_file_path = f'{ConfigManager.get_config_value(self.config, "MY_DATA_FOLDER", "/run/data/")}referees/details/referees.json'

            if initial:
                self.referee_file_watch_observer = watchFileChange(referee_file_path, self.should_load_referees_file)

            self.handleRefereeData.loadActiveRefereeDetails(referee_file_path, None, initial)
            self.referees_file_changed = False

        except Exception as ex:
            self.logger.error(f'load_metadata', ex)

    def should_load_referees_file(self, file_path, file=None):
        """
        Callback for file watcher.
        """
        self.referees_file_changed = True
    
    def reset_progress(self):
        """
        Reset progress counter.
        """
        self.completed_referees = 0

    def simulate_dynamic_progress(self, info_no_result):
        """
        Simulate dynamic progress display.
        """
        self.completed_referees += 1
        elapsed_time = helpers.stopwatchElapsed(f'Loop time')
        progress = f"\rProgress: [{'#' * self.completed_referees}{'.' * (self.active_referees - self.completed_referees)}] {self.completed_referees}/{self.active_referees} {elapsed_time}"
        sys.stdout.write(progress)
        sys.stdout.flush()
        if info_no_result or self.completed_referees == self.active_referees:
            print()

def create_ref_portal_service_di(container: AppContainer = None) -> RefPortalServiceDI:
    """
    Factory function to create RefPortalServiceDI with dependency injection.
    
    Args:
        container: Optional AppContainer instance
        
    Returns:
        RefPortalServiceDI instance
    """
    return RefPortalServiceDI(container)

if __name__ == "__main__":
    app = None
    try:
        # Create service with dependency injection
        ref_portal_service = RefPortalServiceDI()
        asyncio.run(ref_portal_service.start())
    except Exception as ex:
        print(f'Main Error:', ex)
        logging.exception('main error')