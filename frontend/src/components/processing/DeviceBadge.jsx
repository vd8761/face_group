import { Cpu, Gauge } from 'lucide-react';
import { formatProcessor } from './formatters';

export default function DeviceBadge({ processor, compact = false }) {
  const label = formatProcessor(processor);
  const isGpu = label === 'GPU';
  const isMixed = label === 'CPU + GPU';
  const className = isGpu ? 'device-badge gpu' : isMixed ? 'device-badge mixed' : 'device-badge cpu';
  const Icon = isGpu || isMixed ? Gauge : Cpu;

  return (
    <span className={className} title={`Processing device: ${label}`}>
      <Icon size={compact ? 11 : 13} />
      {label}
    </span>
  );
}
