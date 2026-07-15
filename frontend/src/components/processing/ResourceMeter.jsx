export default function ResourceMeter({ label, value, detail, tone = 'cpu' }) {
  const normalized = Math.min(100, Math.max(0, Number(value) || 0));
  return (
    <div className="resource-meter">
      <div className="resource-meter-label">
        <span>{label}</span>
        <strong>{normalized.toFixed(0)}%</strong>
      </div>
      <progress className={`resource-meter-progress ${tone}`} max="100" value={normalized} aria-label={`${label} utilization`} />
      {detail && <span className="resource-meter-detail">{detail}</span>}
    </div>
  );
}
