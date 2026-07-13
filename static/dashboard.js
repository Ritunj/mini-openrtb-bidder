/*
Purpose:        Front-end logic for the dashboard (Phase 5).

Responsibilities:
  - Load campaigns, creatives, the auction log and impressions from the
    /api/* endpoints and render them into tables
  - Render ALL data as plain text (textContent, never innerHTML), so
    user-supplied ad markup can never inject scripts into this page
  - Test console: send a bid request to POST /openrtb/bid, show the
    protocol verdict (200 / 204 / 400), then optionally fire the win
    notice (nurl) to complete the auction lifecycle

Dependencies:   None (vanilla JavaScript, Fetch API).
*/

"use strict";

const SAMPLE_BID_REQUEST = {
  id: "req-demo-1",
  imp: [{ id: "1", banner: { w: 300, h: 250 }, bidfloor: 1.0 }],
  site: { domain: "news.example.com", cat: ["IAB12"] },
  device: { devicetype: 4, os: "Android", geo: { country: "IND" } },
  user: { id: "user-abc" },
};

let lastNurl = null; // win-notice URL from the most recent winning bid

/* --------------------------- small helpers --------------------------- */

function el(id) {
  return document.getElementById(id);
}

function textCell(value, mono) {
  // Every cell goes through textContent: this is the anti-injection guard.
  const td = document.createElement("td");
  td.textContent = (value === null || value === undefined) ? "\u2014" : String(value);
  if (mono) {
    td.classList.add("mono");
  }
  return td;
}

function badgeCell(kind) {
  // kind comes from our own server-side enums ("active", "bid", ...),
  // so it is safe to use inside a class name.
  const td = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = "badge badge-" + kind;
  badge.textContent = kind;
  td.appendChild(badge);
  return td;
}

function money(value) {
  return (value === null || value === undefined) ? null : Number(value).toFixed(2);
}

function shortTime(iso) {
  // "2026-07-06T04:58:22+00:00" -> "2026-07-06 04:58:22"
  return String(iso).replace("T", " ").replace("+00:00", "");
}

async function fetchJSON(path) {
  const response = await fetch(path);
  return response.json();
}

function fillTable(tbodyId, emptyId, rows) {
  el(tbodyId).replaceChildren(...rows);
  el(emptyId).hidden = rows.length > 0;
}

/* ----------------------------- rendering ----------------------------- */

function targetingSummary(targeting) {
  const t = targeting || {};
  const parts = [];
  if ((t.countries || []).length) parts.push(t.countries.join(", "));
  if ((t.device_types || []).length) parts.push(t.device_types.join(", "));
  if ((t.site_categories || []).length) parts.push(t.site_categories.join(", "));
  return parts.length ? parts.join(" \u00b7 ") : "everyone";
}

function renderCampaigns(campaigns) {
  fillTable("campaigns-body", "campaigns-empty", campaigns.map(function (c) {
    const tr = document.createElement("tr");
    tr.append(
      textCell(c.id, true),
      textCell(c.name),
      badgeCell(c.status),
      textCell(money(c.cpm_bid), true),
      textCell(targetingSummary(c.targeting)),
    );
    return tr;
  }));
}

function renderCreatives(creatives) {
  fillTable("creatives-body", "creatives-empty", creatives.map(function (cr) {
    const tr = document.createElement("tr");
    tr.append(
      textCell(cr.id, true),
      textCell(cr.campaign_id, true),
      textCell(cr.name),
      textCell(cr.w + "\u00d7" + cr.h, true),
    );
    return tr;
  }));
}

function renderLog(entries) {
  fillTable("log-body", "log-empty", entries.map(function (e) {
    const tr = document.createElement("tr");
    tr.append(
      textCell(shortTime(e.timestamp), true),
      textCell(e.request_id, true),
      badgeCell(e.result),
      textCell(e.campaign_id, true),
      textCell(money(e.price), true),
      textCell(e.reason),
    );
    return tr;
  }));
}

function renderImpressions(impressions) {
  fillTable("impressions-body", "impressions-empty", impressions.map(function (i) {
    const tr = document.createElement("tr");
    tr.append(
      textCell(shortTime(i.timestamp), true),
      textCell(i.bid_id, true),
      textCell(i.campaign_id, true),
      textCell(money(i.bid_price), true),
      textCell(money(i.win_price), true),
    );
    return tr;
  }));
}

async function loadAll() {
  try {
    const [campaigns, creatives, log, impressions] = await Promise.all([
      fetchJSON("/api/campaigns"),
      fetchJSON("/api/creatives"),
      fetchJSON("/api/log"),
      fetchJSON("/api/impressions"),
    ]);
    renderCampaigns(campaigns);
    renderCreatives(creatives);
    renderLog(log);
    renderImpressions(impressions);
  } catch (error) {
    console.error("Could not load dashboard data:", error);
  }
}

/* --------------------------- test console ---------------------------- */

async function sendBidRequest() {
  const statusLine = el("bid-status");
  const responseBox = el("bid-response");
  el("bid-result").hidden = false;
  el("win-panel").hidden = true;
  el("win-response").hidden = true;
  lastNurl = null;

  try {
    // The textarea is sent EXACTLY as typed: if the JSON is broken, the
    // SERVER's validation answers. The demo shows the real API at work.
    const response = await fetch("/openrtb/bid", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: el("bid-input").value,
    });

    if (response.status === 200) {
      const data = await response.json();
      statusLine.textContent = "HTTP 200 \u2014 we bid! OpenRTB response:";
      statusLine.className = "status-line status-ok";
      responseBox.textContent = JSON.stringify(data, null, 2);
      responseBox.hidden = false;
      const bid = data.seatbid[0].bid[0];
      lastNurl = bid.nurl;
      el("win-price").value = bid.price.toFixed(2);
      el("win-panel").hidden = false;
    } else if (response.status === 204) {
      statusLine.textContent =
        "HTTP 204 No Content \u2014 valid request, but no campaign bid. " +
        "The newest auction log entry says why.";
      statusLine.className = "status-line status-nobid";
      responseBox.hidden = true;
    } else {
      const data = await response.json();
      statusLine.textContent = "HTTP " + response.status + " \u2014 request rejected:";
      statusLine.className = "status-line status-error";
      responseBox.textContent = JSON.stringify(data, null, 2);
      responseBox.hidden = false;
    }
  } catch (error) {
    statusLine.textContent = "Could not reach the server \u2014 is app.py running?";
    statusLine.className = "status-line status-error";
    responseBox.hidden = true;
  }
  await loadAll();
}

async function fireWinNotice() {
  if (!lastNurl) {
    return;
  }
  const price = el("win-price").value;
  // Do exactly what the exchange does: substitute the macro, fire the URL.
  const url = lastNurl.replace("${AUCTION_PRICE}", encodeURIComponent(price));
  const box = el("win-response");
  try {
    const response = await fetch(url);
    const data = await response.json();
    box.textContent = "Impression recorded:\n" + JSON.stringify(data, null, 2);
  } catch (error) {
    box.textContent = "Win notice failed \u2014 is app.py running?";
  }
  box.hidden = false;
  await loadAll();
}

/* ------------------------------- init -------------------------------- */

el("bid-input").value = JSON.stringify(SAMPLE_BID_REQUEST, null, 2);
el("refresh-btn").addEventListener("click", loadAll);
el("send-bid-btn").addEventListener("click", sendBidRequest);
el("fire-win-btn").addEventListener("click", fireWinNotice);
loadAll();
