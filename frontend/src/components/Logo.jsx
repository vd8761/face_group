export default function Logo({ light = false, style = {}, size = 'md', align = 'left' }) {
  const heights = { sm: 36, md: 48, lg: 64 };
  const baseH = heights[size] || heights.md;
  // Previously we used transform: scale(1.8), which didn't affect DOM width and caused overlaps.
  // Now we just multiply the height directly.
  const h = baseH * 1.8;
  
  return (
    <div style={{ 
      display: 'inline-flex', 
      alignItems: 'center',
      justifyContent: align === 'center' ? 'center' : 'flex-start',
      height: h, 
      ...style 
    }}>
      <img
        src="/urface_logo.png"
        alt="UrFace"
        style={{
          display: 'block',
          height: h, 
          width: 'auto',
          filter: light ? 'brightness(0) invert(1)' : 'none',
          mixBlendMode: light ? 'screen' : 'multiply',
          transition: 'filter 0.2s',
        }}
        onError={e => {
          e.currentTarget.style.display = 'none';
        }}
      />
    </div>
  );
}
