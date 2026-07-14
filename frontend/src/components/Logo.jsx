import { ScanFace } from 'lucide-react';

export default function Logo({ light = false, style = {}, hideText = false }) {
  const textColor = light ? '#ffffff' : 'var(--text-main)';
  
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', ...style }}>
      {/* The U-Face / Constellation Emblem */}
      <div style={{ 
        background: 'linear-gradient(135deg, var(--primary), #34D6FF)',
        padding: '0.35rem', 
        borderRadius: '0.4rem',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        boxShadow: '0 4px 10px rgba(91, 95, 239, 0.2)'
      }}>
        <ScanFace size={20} color="#ffffff" strokeWidth={2.5} />
      </div>
      
      {/* Typography */}
      {!hideText && (
        <div style={{ 
          display: 'flex', alignItems: 'center', gap: '0.15rem',
          fontSize: '1.6rem', fontWeight: 900, 
          fontFamily: "'Outfit', system-ui, sans-serif",
          letterSpacing: '-0.04em', lineHeight: 1,
          marginTop: '0.15rem'
        }}>
          <span style={{ color: textColor }}>
            UrFace
          </span>
          <span style={{ 
            background: 'linear-gradient(90deg, #8B5CF6, #06B6D4)', 
            WebkitBackgroundClip: 'text', 
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            marginLeft: '0.15rem'
          }}>
            AI
          </span>
        </div>
      )}
    </div>
  );
}
