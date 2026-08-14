/**
 * Thin fetch wrapper for the CheerApp backend's REST contract
 * (../backend/README.md). Kept separate from main.js so the join flow
 * there reads as orchestration, not fetch plumbing.
 */

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export class ApiClient {
  /** @param {string} baseUrl e.g. "http://localhost:5100" (no trailing slash) */
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
  }

  async getEvent(eventId) {
    return this._get(`/events/${encodeURIComponent(eventId)}`);
  }

  /** @returns {Promise<{zoneId: string}>} */
  async checkin(eventId, qrToken) {
    return this._post(`/events/${encodeURIComponent(eventId)}/checkin`, { qrToken });
  }

  /** @returns {Promise<object|null>} the published Show, or null if none yet (404) */
  async getShow(eventId) {
    try {
      return await this._get(`/events/${encodeURIComponent(eventId)}/show`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  }

  async _get(path) {
    const res = await fetch(this.baseUrl + path, { cache: "no-store" });
    return this._handle(res);
  }

  async _post(path, body) {
    const res = await fetch(this.baseUrl + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return this._handle(res);
  }

  async _handle(res) {
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new ApiError(detail?.detail ? JSON.stringify(detail.detail) : res.statusText, res.status);
    }
    return res.json();
  }
}
