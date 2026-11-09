(() => {
  "use strict";

  document.addEventListener("DOMContentLoaded", () => {
    const host = document.getElementById("price-chart");
    if (!host) return;

    const form = document.getElementById("chart-filters");
    const HTML_NS = "http://www.w3.org/1999/xhtml";
    const SVG_NS = "http://www.w3.org/2000/svg";
    const colors = { "59": "#2b6cb0", "84": "#c05621" };
    const natureLabels = { ACTUAL: "실거래", ASKING: "호가" };
    const typeLabels = { SALE: "매매", JEONSE: "전세", WOLSE: "월세" };
    const numberFormat = new Intl.NumberFormat("ko-KR", {
      maximumFractionDigits: 2
    });
    const day = 86400000;

    let requestId = 0;
    let state = null;
    let message = "";
    let resizeTimer;
    let tooltip;
    let tooltipPoint = null;

    host.style.position = "relative";

    function html(tag, text) {
      const element = document.createElementNS(HTML_NS, tag);
      if (text !== undefined) element.textContent = text;
      return element;
    }

    function svgElement(tag, attributes = {}, text) {
      const element = document.createElementNS(SVG_NS, tag);
      for (const [name, value] of Object.entries(attributes)) {
        element.setAttribute(name, String(value));
      }
      if (text !== undefined) element.textContent = text;
      return element;
    }

    function axisAmount(value) {
      return value >= 100000000
        ? `${numberFormat.format(value / 100000000)}억`
        : `${numberFormat.format(value / 10000)}만`;
    }

    function amount(value) {
      if (!Number.isFinite(value)) return "정보 없음";
      const won = Math.round(value);
      const eok = Math.floor(won / 100000000);
      const remainder = won % 100000000;
      if (!eok) {
        return won >= 10000
          ? `${numberFormat.format(won / 10000)}만원`
          : `${numberFormat.format(won)}원`;
      }
      return remainder
        ? `${numberFormat.format(eok)}억 ${numberFormat.format(remainder / 10000)}만원`
        : `${numberFormat.format(eok)}억`;
    }

    function pointAmount(point, txType) {
      if (txType === "WOLSE") {
        return `보증금 ${amount(point.deposit_krw)} / 월 ${amount(point.monthly_rent_krw)}`;
      }
      return amount(txType === "SALE" ? point.price_krw : point.deposit_krw);
    }

    function readFilters() {
      const data = form ? new FormData(form) : null;
      const selectedType = data ? String(data.get("tx_type") || "SALE") : "SALE";
      return {
        txType: Object.prototype.hasOwnProperty.call(typeLabels, selectedType)
          ? selectedType
          : "SALE",
        sizes: data ? data.getAll("size_class").map(String) : ["59", "84"],
        natures: data ? data.getAll("nature").map(String) : ["ACTUAL", "ASKING"]
      };
    }

    function validAmount(value) {
      return typeof value === "number" && Number.isFinite(value) && value >= 0;
    }

    function prepare(payload, filters) {
      const groups = new Map();
      const fields = filters.txType === "WOLSE"
        ? ["deposit_krw", "monthly_rent_krw"]
        : [filters.txType === "SALE" ? "price_krw" : "deposit_krw"];

      for (const item of payload.series) {
        if (!item || !Array.isArray(item.points)) continue;
        const size = String(item.size_class);
        const nature = String(item.nature);
        if (!filters.sizes.includes(size) || !filters.natures.includes(nature)) continue;
        if (!Object.prototype.hasOwnProperty.call(colors, size)) continue;
        if (!Object.prototype.hasOwnProperty.call(natureLabels, nature)) continue;

        const key = `${size}:${nature}`;
        let group = groups.get(key);
        if (!group) {
          group = { size, nature, stale: false, updates: new Set(), points: [] };
          groups.set(key, group);
        }

        group.stale = group.stale || item.stale === true;
        if (item.stale === true && item.last_updated) {
          group.updates.add(String(item.last_updated));
        }

        for (const point of item.points) {
          if (!point || typeof point.date !== "string") continue;
          const time = Date.parse(point.date);
          if (!Number.isFinite(time) || !fields.every(field => validAmount(point[field]))) {
            continue;
          }
          group.points.push({ ...point, time });
        }
      }

      return {
        txType: filters.txType,
        series: Array.from(groups.values())
          .filter(group => group.points.length)
          .map(group => {
            group.points.sort((a, b) => a.time - b.time);
            return group;
          })
      };
    }

    function hideTooltip() {
      if (tooltip) tooltip.hidden = true;
      tooltipPoint = null;
    }

    function positionTooltip(clientX, clientY) {
      const rect = host.getBoundingClientRect();
      const width = tooltip.offsetWidth;
      const left = Math.max(0, Math.min(clientX - rect.left + 12, rect.width - width));
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${Math.max(0, clientY - rect.top + 12)}px`;
    }

    function showTooltip(point, group, event, marker) {
      const lines = [
        point.date,
        `전용 ${group.size}㎡ · ${natureLabels[group.nature]}`,
        pointAmount(point, state.txType),
        `층: ${point.floor == null ? "-" : String(point.floor)}`,
        `출처: ${point.source_name == null ? "-" : String(point.source_name)}`,
        `상태: ${point.status == null ? "-" : String(point.status)}`
      ];
      if (point.is_estimate === true) lines.push("추정");
      tooltip.textContent = lines.join("\n");
      tooltip.hidden = false;
      tooltipPoint = point;

      const rect = marker.getBoundingClientRect();
      positionTooltip(
        Number.isFinite(event.clientX) ? event.clientX : rect.left + rect.width / 2,
        Number.isFinite(event.clientY) ? event.clientY : rect.bottom
      );
    }

    function navigate(point) {
      if (typeof point.detail_url !== "string" || !point.detail_url.trim()) return;
      try {
        const target = new URL(point.detail_url, window.location.href);
        if (target.origin === window.location.origin &&
            (target.protocol === "http:" || target.protocol === "https:")) {
          window.location.assign(target.href);
        }
      } catch (_) {}
    }

    function attachMarkerEvents(marker, point, group) {
      let touch = false;

      marker.addEventListener("pointerdown", event => {
        touch = event.pointerType === "touch";
      });
      marker.addEventListener("pointerenter", event => {
        if (event.pointerType !== "touch") showTooltip(point, group, event, marker);
      });
      marker.addEventListener("pointermove", event => {
        if (event.pointerType !== "touch" && tooltipPoint === point) {
          positionTooltip(event.clientX, event.clientY);
        }
      });
      marker.addEventListener("pointerleave", event => {
        if (event.pointerType !== "touch") hideTooltip();
      });
      marker.addEventListener("focus", event => {
        if (!touch) showTooltip(point, group, event, marker);
      });
      marker.addEventListener("blur", hideTooltip);
      marker.addEventListener("click", event => {
        if ((touch || event.pointerType === "touch") && tooltipPoint !== point) {
          showTooltip(point, group, event, marker);
          touch = false;
          return;
        }
        touch = false;
        navigate(point);
      });
      marker.addEventListener("keydown", event => {
        if (event.key === "Enter") {
          event.preventDefault();
          navigate(point);
        } else if (event.key === " " || event.key === "Spacebar") {
          event.preventDefault();
          showTooltip(point, group, event, marker);
        } else if (event.key === "Escape") {
          hideTooltip();
        }
      });
    }

    function drawChart(title, field, timeMin, timeMax) {
      const width = Math.max(320, host.clientWidth || 640);
      const height = 290;
      const margin = { top: 42, right: 28, bottom: 44, left: 76 };
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const svg = svgElement("svg", {
        viewBox: `0 0 ${width} ${height}`,
        width: "100%",
        role: "img",
        "aria-label": `${typeLabels[state.txType]} ${title} 가격 이력`
      });
      svg.style.display = "block";
      svg.style.height = "auto";
      svg.appendChild(svgElement("title", {}, `${title} 가격 이력`));
      svg.appendChild(svgElement("text", {
        x: margin.left,
        y: 24,
        "font-size": 16,
        "font-weight": 600,
        fill: "#222"
      }, title));

      let valueMin = Infinity;
      let valueMax = -Infinity;
      for (const group of state.series) {
        for (const point of group.points) {
          valueMin = Math.min(valueMin, point[field]);
          valueMax = Math.max(valueMax, point[field]);
        }
      }

      const padding = valueMax === valueMin
        ? Math.max(valueMax * 0.1, 10000)
        : (valueMax - valueMin) * 0.12;
      const yMin = Math.max(0, valueMin - padding);
      const yMax = valueMax + padding;
      const x = time => margin.left + (time - timeMin) / (timeMax - timeMin) * plotWidth;
      const y = value => margin.top + (yMax - value) / (yMax - yMin) * plotHeight;
      const bottom = margin.top + plotHeight;

      for (let i = 0; i <= 4; i += 1) {
        const value = yMin + (yMax - yMin) * i / 4;
        const yy = y(value);
        svg.appendChild(svgElement("line", {
          x1: margin.left, x2: width - margin.right,
          y1: yy, y2: yy, stroke: "#e2e8f0"
        }));
        svg.appendChild(svgElement("text", {
          x: margin.left - 8, y: yy + 4,
          "text-anchor": "end", "font-size": 11, fill: "#555"
        }, axisAmount(value)));
      }

      svg.appendChild(svgElement("path", {
        d: `M ${margin.left} ${margin.top} V ${bottom} H ${width - margin.right}`,
        fill: "none",
        stroke: "#718096"
      }));

      const tickCount = Math.max(2, Math.min(6, Math.floor(plotWidth / 90)));
      const seenMonths = new Set();
      for (let i = 0; i < tickCount; i += 1) {
        const time = timeMin + (timeMax - timeMin) * i / (tickCount - 1);
        const label = new Date(time).toISOString().slice(0, 7);
        if (seenMonths.has(label)) continue;
        seenMonths.add(label);
        const xx = x(time);
        svg.appendChild(svgElement("line", {
          x1: xx, x2: xx, y1: bottom, y2: bottom + 5, stroke: "#718096"
        }));
        svg.appendChild(svgElement("text", {
          x: xx, y: bottom + 22,
          "text-anchor": "middle", "font-size": 11, fill: "#555"
        }, label));
      }

      for (const group of state.series) {
        const color = colors[group.size];
        const asking = group.nature === "ASKING";
        const active = group.points.filter(point => point.status !== "CANCELLED");
        if (active.length) {
          const line = svgElement("polyline", {
            points: active.map(point => `${x(point.time)},${y(point[field])}`).join(" "),
            fill: "none",
            stroke: color,
            "stroke-width": 2,
            "vector-effect": "non-scaling-stroke"
          });
          if (asking) line.setAttribute("stroke-dasharray", "6 4");
          svg.appendChild(line);
        }

        for (const point of group.points) {
          const xx = x(point.time);
          const yy = y(point[field]);
          const cancelled = point.status === "CANCELLED";
          const marker = svgElement("g", {
            tabindex: 0,
            role: "link",
            "aria-label": `${point.date}, 전용 ${group.size}㎡, ${natureLabels[group.nature]}, ${pointAmount(point, state.txType)}, ${point.status || ""}${point.is_estimate === true ? ", 추정" : ""}`
          });
          marker.style.cursor = "pointer";
          marker.appendChild(svgElement("circle", {
            cx: xx, cy: yy, r: 11, fill: "transparent"
          }));

          if (cancelled) {
            marker.appendChild(svgElement("text", {
              x: xx, y: yy,
              "text-anchor": "middle",
              "dominant-baseline": "central",
              "font-size": 21,
              "font-weight": 600,
              fill: "#888"
            }, "×"));
          } else {
            marker.appendChild(svgElement("circle", {
              cx: xx, cy: yy, r: 4.5,
              fill: asking ? "#fff" : color,
              stroke: color,
              "stroke-width": 2
            }));
          }

          if (point.is_estimate === true) {
            marker.appendChild(svgElement("text", {
              x: xx + 8, y: yy - 7,
              "font-size": 10,
              fill: cancelled ? "#888" : color
            }, "추정"));
          }

          attachMarkerEvents(marker, point, group);
          svg.appendChild(marker);
        }
      }

      host.appendChild(svg);
    }

    function render() {
      hideTooltip();
      host.replaceChildren();

      if (!state || !state.series.length) {
        const notice = html("div", message || "표시할 기록이 없습니다");
        notice.setAttribute("role", "status");
        host.appendChild(notice);
        return;
      }

      const legend = html("div");
      legend.setAttribute("aria-label", "범례");
      legend.style.display = "flex";
      legend.style.flexWrap = "wrap";
      legend.style.gap = "8px 20px";

      for (const group of state.series) {
        const entry = html("span");
        const swatch = html("span", group.nature === "ACTUAL" ? "●" : "○");
        swatch.style.color = colors[group.size];
        swatch.style.display = "inline-block";
        swatch.style.width = "28px";
        swatch.style.textAlign = "center";
        swatch.style.borderBottom = `2px ${group.nature === "ACTUAL" ? "solid" : "dashed"} ${colors[group.size]}`;
        entry.appendChild(swatch);
        entry.appendChild(html("span", ` 전용 ${group.size}㎡ ${natureLabels[group.nature]}`));
        if (group.stale) {
          const stale = html("span", ` (갱신 지연) ${Array.from(group.updates).sort().join(", ") || "갱신일 정보 없음"}`);
          stale.style.color = "#c53030";
          entry.appendChild(stale);
        }
        legend.appendChild(entry);
      }
      host.appendChild(legend);

      let timeMin = Infinity;
      let timeMax = -Infinity;
      for (const group of state.series) {
        for (const point of group.points) {
          timeMin = Math.min(timeMin, point.time);
          timeMax = Math.max(timeMax, point.time);
        }
      }
      if (timeMin === timeMax) {
        timeMin -= 15 * day;
        timeMax += 15 * day;
      }

      if (state.txType === "WOLSE") {
        drawChart("보증금", "deposit_krw", timeMin, timeMax);
        drawChart("월세", "monthly_rent_krw", timeMin, timeMax);
      } else {
        drawChart(
          state.txType === "SALE" ? "매매가" : "전세 보증금",
          state.txType === "SALE" ? "price_krw" : "deposit_krw",
          timeMin,
          timeMax
        );
      }

      tooltip = html("div");
      tooltip.hidden = true;
      tooltip.setAttribute("role", "tooltip");
      Object.assign(tooltip.style, {
        position: "absolute",
        zIndex: "10",
        pointerEvents: "none",
        whiteSpace: "pre-line",
        overflowWrap: "anywhere",
        boxSizing: "border-box",
        maxWidth: "100%",
        padding: "10px 12px",
        border: "1px solid #cbd5e0",
        borderRadius: "6px",
        background: "#fff",
        color: "#222",
        fontSize: "13px",
        lineHeight: "1.6",
        boxShadow: "0 2px 8px rgba(0,0,0,0.15)"
      });
      host.appendChild(tooltip);
    }

    async function load() {
      const currentRequest = ++requestId;
      const filters = readFilters();
      const params = new URLSearchParams();
      params.set("tx_type", filters.txType);
      filters.sizes.forEach(size => params.append("size_class", size));
      filters.natures.forEach(nature => params.append("nature", nature));

      state = null;
      message = "불러오는 중...";
      host.setAttribute("aria-busy", "true");
      render();

      try {
        const url = host.dataset.seriesUrl;
        if (!url) throw new Error("Missing URL");
        const parsed = new URL(url, window.location.href);
        if (parsed.origin !== window.location.origin ||
            !["http:", "https:"].includes(parsed.protocol)) {
          throw new Error("Invalid URL");
        }

        const response = await fetch(url + "?" + params);
        if (!response.ok) throw new Error("Request failed");
        const payload = await response.json();
        if (currentRequest !== requestId) return;
        if (!payload || payload.tx_type !== filters.txType || !Array.isArray(payload.series)) {
          throw new Error("Invalid response");
        }

        state = prepare(payload, filters);
        message = "";
      } catch (_) {
        if (currentRequest !== requestId) return;
        state = null;
        message = "가격 기록을 불러오지 못했습니다";
      }

      if (currentRequest === requestId) {
        host.setAttribute("aria-busy", "false");
        render();
      }
    }

    if (form) {
      form.addEventListener("change", load);
      form.addEventListener("submit", event => {
        event.preventDefault();
        load();
      });
    }

    window.addEventListener("resize", () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(render, 150);
    });

    document.addEventListener("pointerdown", event => {
      if (!host.contains(event.target)) hideTooltip();
    });

    load();
  });
})();
