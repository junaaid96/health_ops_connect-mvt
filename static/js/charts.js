/* Chart helpers built on Chart.js.
 * Conventions: 2px lines, >=8px markers with a surface ring, hairline solid
 * grid, one y-axis per chart, crosshair + all-series tooltip, legend only
 * when there are 2+ series. Colours come from CSS custom properties on
 * .viz-root so light/dark are chosen, not flipped. */
(function () {
  "use strict";
  const charts = [];

  function tokens(el) {
    const root = el.closest(".viz-root") || document.documentElement;
    const cs = getComputedStyle(root);
    const v = (name) => cs.getPropertyValue(name).trim();
    return {
      surface: v("--viz-surface"), grid: v("--viz-grid"), text: v("--viz-text"), muted: v("--viz-muted"),
      series: [v("--viz-series-1"), v("--viz-series-2"), v("--viz-series-3")],
    };
  }

  const crosshair = {
    id: "crosshair",
    afterDatasetsDraw(chart) {
      const active = chart.tooltip && chart.tooltip.getActiveElements();
      if (!active || !active.length || chart.config.type !== "line") return;
      const x = active[0].element.x;
      const { top, bottom } = chart.chartArea;
      const ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = tokens(chart.canvas).muted;
      ctx.globalAlpha = 0.5;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
      ctx.restore();
    },
  };

  // Direct label at the end of each line (the value), in text ink, not series colour.
  const endLabels = {
    id: "endLabels",
    afterDatasetsDraw(chart, _args, opts) {
      if (!opts || !opts.enabled || chart.config.type !== "line") return;
      const t = tokens(chart.canvas);
      const ctx = chart.ctx;
      chart.data.datasets.forEach((ds, i) => {
        const meta = chart.getDatasetMeta(i);
        const last = [...meta.data].reverse().find((p, idx) => ds.data[meta.data.length - 1 - idx] != null);
        if (!last) return;
        const value = ds.data[meta.data.indexOf(last)];
        ctx.save();
        ctx.font = "600 12px 'Plus Jakarta Sans', system-ui, sans-serif";
        ctx.fillStyle = t.text;
        ctx.textBaseline = "middle";
        ctx.fillText(String(value), last.x + 8, last.y);
        ctx.restore();
      });
    },
  };

  function baseOptions(t, { unit = "", legend = false, stacked = false, endLabel = false, bar = false } = {}) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      layout: { padding: { right: endLabel ? 36 : 8, top: 8 } },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: legend
          ? { display: true, position: "top", align: "start",
              // Keys mirror the mark: a short stroke for lines, a small rect for bars.
              labels: { color: t.text, boxWidth: bar ? 10 : 16, boxHeight: bar ? 10 : 2, font: { size: 12 } } }
          : { display: false },
        tooltip: {
          backgroundColor: t.surface, titleColor: t.muted, bodyColor: t.text, borderColor: t.grid, borderWidth: 1,
          padding: 10, displayColors: true, boxWidth: bar ? 8 : 12, boxHeight: bar ? 8 : 2, boxPadding: 4,
          bodyFont: { weight: "600" },
          callbacks: { label: (c) => ` ${c.formattedValue}${unit ? " " + unit : ""}  ${c.dataset.label}` },
        },
        endLabels: { enabled: endLabel },
      },
      scales: {
        x: { stacked, grid: { display: false }, border: { color: t.grid },
             ticks: { color: t.muted, maxRotation: 0, autoSkipPadding: 16, font: { size: 11 } } },
        y: { stacked, grid: { color: t.grid, lineWidth: 1 }, border: { display: false },
             ticks: { color: t.muted, font: { size: 11 }, maxTicksLimit: 5, precision: 0 } },
      },
    };
  }

  function lineChart(canvas, cfg) {
    const t = tokens(canvas);
    const datasets = cfg.series.map((s, i) => ({
      label: s.label, data: s.data, borderColor: t.series[s.slot ?? i], backgroundColor: t.series[s.slot ?? i],
      borderWidth: 2, tension: 0.3, spanGaps: true,
      pointRadius: 4, pointHoverRadius: 6, pointBorderColor: t.surface, pointBorderWidth: 2, pointHitRadius: 12,
    }));
    return new Chart(canvas, {
      type: "line",
      data: { labels: cfg.labels, datasets },
      options: baseOptions(t, { unit: cfg.unit, legend: cfg.series.length > 1, endLabel: true }),
      plugins: [crosshair, endLabels],
    });
  }

  function barChart(canvas, cfg) {
    const t = tokens(canvas);
    const stacked = cfg.series.length > 1;
    const datasets = cfg.series.map((s, i) => ({
      label: s.label, data: s.data, backgroundColor: t.series[s.slot ?? i],
      borderColor: t.surface, borderWidth: stacked ? { top: 2 } : 0, borderSkipped: "bottom",
      borderRadius: (ctx) => (ctx.datasetIndex === cfg.series.length - 1 ? { topLeft: 4, topRight: 4 } : 0),
      maxBarThickness: 24,
    }));
    return new Chart(canvas, {
      type: "bar",
      data: { labels: cfg.labels, datasets },
      options: baseOptions(t, { legend: stacked, stacked, bar: true }),
    });
  }

  function mount() {
    charts.splice(0).forEach((c) => c.destroy());
    document.querySelectorAll("canvas[data-chart]").forEach((canvas) => {
      const cfg = JSON.parse(document.getElementById(canvas.dataset.config).textContent);
      const build = canvas.dataset.chart === "bar" ? barChart : lineChart;
      charts.push(build(canvas, cfg));
    });
  }

  document.addEventListener("DOMContentLoaded", mount);
  document.addEventListener("themechange", () => requestAnimationFrame(mount));
})();
