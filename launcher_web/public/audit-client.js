(function () {
  const launcherOrigin = `${window.location.protocol}//${window.location.hostname}:8890`;

  async function log(event) {
    if (!event || !event.module || !event.summary) return false;
    try {
      const response = await fetch(`${launcherOrigin}/api/audit/event`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          module: event.module,
          eventType: event.eventType || "item.update",
          entityType: event.entityType || "",
          entityId: event.entityId || "",
          summary: event.summary,
          details: event.details || {},
        }),
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  window.AgricolaAudit = { log };
})();
