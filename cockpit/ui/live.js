"use strict";
// État du flux, sans accès au réseau ni à la page : testable seul. « En direct » n'est atteint qu'après un flux ouvert ET des données à jour.
(function (root) {
  const initial = () => ({ phase: "connecting", instance: null, seq: null, heartbeat: null, loss: null, duplicates: 0, lostAt: null });
  const lost = (s, why, at) => ({ ...s, loss: { why, at } });
  function reduce(s, ev) {
    switch (ev.type) {
      case "hello": {
        const known = s.instance !== null;
        const same = s.instance === ev.instance && s.seq === ev.seq;
        const next = { ...s, heartbeat: ev.heartbeat ?? s.heartbeat, lostAt: null };
        if (known && ev.instance !== s.instance) return { state: { ...lost(next, "Serveur redémarré", ev.at), instance: ev.instance, phase: "resync" }, load: true };
        if (known && same) return { state: { ...next, phase: "live" }, load: false }; // rien n'a pu être manqué : même instance, même séquence
        if (known && ev.resync) return { state: { ...lost(next, "Reprise sans preuve de continuité", ev.at), phase: "resync" }, load: true };
        if (!known) return { state: { ...next, instance: ev.instance, phase: "resync" }, load: true };
        return { state: { ...next, phase: "resync_replay" }, load: false }; // le serveur rejoue ce qui manque : l'état n'est à jour qu'à la fin
      }
      case "update": {
        if (s.seq === null || s.phase === "resync") return { state: s, load: true };
        if (ev.seq <= s.seq) return { state: { ...s, duplicates: s.duplicates + 1 }, load: false };
        if (ev.seq === s.seq + 1) return { state: { ...s, seq: ev.seq, phase: "resync" }, load: true };
        return { state: { ...lost(s, `${ev.seq - s.seq - 1} mise(s) à jour manquante(s)`, ev.at), phase: "resync" }, load: true };
      }
      case "lost":
        return { state: { ...lost(s, "Mises à jour perdues par le serveur", ev.at), phase: "resync" }, load: true };
      case "ping":
        if (s.phase === "resync_replay" && ev.seq === s.seq) return { state: { ...s, phase: "live" }, load: false };
        if (s.seq !== null && ev.seq > s.seq && (s.phase === "live" || s.phase === "resync_replay")) return { state: { ...lost(s, "Mise à jour non reçue", ev.at), phase: "resync" }, load: true };
        return { state: s, load: false };
      case "snapshot":
        if (s.instance !== null && ev.instance !== s.instance) return { state: { ...lost(s, "Serveur redémarré", ev.at), instance: ev.instance, seq: ev.seq, phase: "live" }, load: false };
        return { state: { ...s, instance: ev.instance, seq: ev.seq, phase: s.phase === "offline" || s.phase === "expired" ? s.phase : "live" }, load: false };
      case "snapshot_failed":
        return { state: { ...s, phase: ev.expired ? "expired" : "stale" }, load: false };
      case "error":
      case "silent":
        return { state: { ...s, phase: s.phase === "expired" ? "expired" : "offline", lostAt: s.lostAt || ev.at }, load: false };
      case "expired":
        return { state: { ...s, phase: "expired", lostAt: s.lostAt || ev.at }, load: false };
      default:
        return { state: s, load: false };
    }
  }
  root.CockpitLive = { initial, reduce, LIVE: "live" };
})(typeof globalThis !== "undefined" ? globalThis : this);
