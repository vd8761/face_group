export default function Logo({ light = false, style = {}, size = 'md' }) {
  const heights = { sm: 36, md: 48, lg: 64 };
  const h = heights[size] || heights.md;
  
  return (
    <div style={{ 
      display: 'inline-flex', 
      alignItems: 'center',
      justifyContent: 'center',
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
          transform: 'scale(1.8)',
          transformOrigin: 'left center',
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
