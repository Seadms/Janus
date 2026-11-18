const valueFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2, signDisplay: "negative" });
const axisFormat = new Intl.NumberFormat(undefined, { maximumSignificantDigits: 4 });
export const clock = new Intl.DateTimeFormat(undefined, { timeStyle: "medium" });
const axisClock = new Intl.DateTimeFormat(undefined, { timeStyle: "medium", hourCycle: "h23" });
const axisDate = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", hourCycle: "h23" });
export const formatValue = value => value == null ? "—" : valueFormat.format(value);

export function createTrace(canvas, tooltip, chart) {
  const ctx = canvas.getContext("2d");
  const theme = getComputedStyle(document.documentElement);
  const accent = theme.getPropertyValue("--accent").trim();
  const grid = theme.getPropertyValue("--slate").trim();
  const labels = theme.getPropertyValue("--silver").trim();
  const area = theme.getPropertyValue("--chart-fill").trim();
  let cursor = null;
  canvas.addEventListener("pointermove", event => { cursor = event.offsetX; });
  canvas.addEventListener("pointerleave", () => { cursor = null; });
  canvas.addEventListener("pointercancel", () => { cursor = null; });

  return function draw(points, start, end, unit, expectedInterval, historical = false) {
    const { width, height } = canvas.getBoundingClientRect();
    if (!width || !height) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const pixelsWide = Math.round(width * ratio);
    const pixelsHigh = Math.round(height * ratio);
    if (canvas.width !== pixelsWide || canvas.height !== pixelsHigh) {
      canvas.width = pixelsWide;
      canvas.height = pixelsHigh;
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    tooltip.hidden = true;

    const left = 48;
    const right = width - 14;
    const top = 16;
    const bottom = height - 32;
    const values = points.map(point => point.value);
    const midpoint = values.at(-1) ?? 0;
    const padding = Math.abs(midpoint) * 0.1 || 1;
    let min = values.length ? Math.min(...values) : 0;
    let max = values.length ? Math.max(...values) : 10;
    if (min === max) {
      min -= padding;
      max += padding;
    }
    const rawStep = (max - min) / 4;
    const magnitude = 10 ** Math.floor(Math.log10(rawStep));
    const step = ([1, 2, 5, 10].find(size => size * magnitude >= rawStep) ?? 10) * magnitude;
    const low = Math.floor(min / step) * step - step * 0.5;
    const high = Math.ceil(max / step) * step + step * 0.5;
    const x = time => left + (right - left) * (time - start) / (end - start);
    const y = value => bottom - (bottom - top) * (value - low) / (high - low);

    ctx.font = "11px Consolas, monospace";
    ctx.textBaseline = "middle";
    ctx.textAlign = "right";
    ctx.fillStyle = labels;
    ctx.strokeStyle = grid;
    ctx.lineWidth = 1;
    for (let index = 0; index < 7; index++) {
      const value = low + (index + 0.5) * step;
      if (value >= high) break;
      const pos = y(value);
      ctx.beginPath();
      ctx.moveTo(left, pos);
      ctx.lineTo(right, pos);
      ctx.stroke();
      ctx.fillText(axisFormat.format(Math.abs(value) < step / 100 ? 0 : value), left - 7, pos, left - 9);
    }

    const multiDay = historical && end - start >= 86400000;
    const intervals = multiDay && width < 520 ? 1 : width < 380 ? 2 : width < 520 ? 3 : 5;
    for (let index = 0; index <= intervals; index++) {
      const time = start + (end - start) * index / intervals;
      ctx.textAlign = index === intervals ? "right" : index === 0 ? "left" : "center";
      ctx.fillText((multiDay ? axisDate : axisClock).format(time), x(time), bottom + 17);
    }

    const fill = ctx.createLinearGradient(0, top, 0, bottom);
    fill.addColorStop(0, area);
    fill.addColorStop(1, "transparent");
    ctx.fillStyle = fill;
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";

    const segments = [];
    let segment = [];
    for (const point of points) {
      if (segment.length && point.time - segment.at(-1).time > expectedInterval) {
        segments.push(segment);
        segment = [];
      }
      segment.push(point);
    }
    if (segment.length) segments.push(segment);

    for (const series of segments) {
      ctx.beginPath();
      series.forEach(({ time, value }, index) => {
        if (index === 0) ctx.moveTo(x(time), y(value));
        else ctx.lineTo(x(time), y(value));
      });
      ctx.stroke();
      ctx.lineTo(x(series.at(-1).time), bottom);
      ctx.lineTo(x(series[0].time), bottom);
      ctx.closePath();
      ctx.fill();
    }

    const latest = points.at(-1);
    if (!latest) return;
    ctx.fillStyle = accent;
    ctx.beginPath();
    ctx.arc(x(latest.time), y(latest.value), 3, 0, 2 * Math.PI);
    ctx.fill();
    if (cursor == null || cursor < x(points[0].time) - 8 || cursor > x(latest.time) + 8) return;

    const nearest = points.reduce((best, point) =>
      Math.abs(x(point.time) - cursor) < Math.abs(x(best.time) - cursor) ? point : best);
    if (Math.abs(x(nearest.time) - cursor) > 12) return;
    const position = x(nearest.time);
    ctx.beginPath();
    ctx.moveTo(position, top);
    ctx.lineTo(position, bottom);
    ctx.strokeStyle = labels;
    ctx.lineWidth = 1;
    ctx.stroke();
    tooltip.textContent = [clock.format(nearest.time), formatValue(nearest.value), unit].filter(Boolean).join("  ");
    tooltip.hidden = false;
    tooltip.style.left = Math.max(0, Math.min(position + 10, chart.clientWidth - tooltip.offsetWidth)) + "px";
  };
}
