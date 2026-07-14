import logoSrc from '../assets/logo.png';

export default function Logo({ style = {}, hideText = false }) {
  // We use the original logo image as requested.
  // We constrain the height to match standard navbar dimensions.
  return (
    <div style={{ display: 'flex', alignItems: 'center', ...style }}>
      <img 
        src={logoSrc} 
        alt="UrFace AI Logo" 
        style={{ height: '36px', width: 'auto', objectFit: 'contain' }} 
      />
    </div>
  );
}
