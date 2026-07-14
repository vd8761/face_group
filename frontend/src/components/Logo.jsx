import { Box } from 'lucide-react';

export default function Logo({ light = false, style = {}, hideText = false }) {
  const textColor = light ? '#ffffff' : '#0B0F19';
  
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', ...style }}>
      {/* The 3D Isometric Blue Icon from the reference */}
      <div style={{ color: '#3b82f6', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Box size={28} strokeWidth={2.5} absoluteStrokeWidth />
      </div>
      
      {/* Typography */}
      {!hideText && (
        <div style={{ 
          display: 'flex', alignItems: 'center', gap: '0.15rem',
          fontSize: '1.75rem', fontWeight: 800, 
          fontFamily: "'Outfit', 'Plus Jakarta Sans', system-ui, sans-serif",
          letterSpacing: '-0.03em', lineHeight: 1,
        }}>
          <span style={{ color: textColor }}>
            UrFace
          </span>
          <span style={{ 
            background: 'linear-gradient(90deg, #7C3AED, #06B6D4)', 
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

