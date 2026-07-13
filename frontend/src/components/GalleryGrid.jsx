import { motion } from 'framer-motion';
import { Check } from 'lucide-react';

export default function GalleryGrid({ photos, selected, onToggle }) {
  return (
    <div className="masonry">
      {photos.map((photo, idx) => (
        <motion.div
          key={photo.id}
          className={`photo-card ${selected.has(photo.id) ? 'selected' : ''}`}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: idx * 0.03, duration: 0.3 }}
          onClick={() => onToggle(photo.id)}
        >
          <img
            src={photo.thumbnail_url}
            alt={photo.filename}
            loading="lazy"
            style={{ borderRadius: '10px' }}
          />
          <div className="photo-card-check">
            <Check size={13} color="#fff" strokeWidth={3} />
          </div>
          {/* Hover overlay */}
          <div style={{
            position: 'absolute', inset: 0,
            background: 'linear-gradient(to top, rgba(0,0,0,0.6) 0%, transparent 50%)',
            opacity: 0,
            transition: 'opacity 0.2s',
            borderRadius: '10px',
            pointerEvents: 'none',
          }} className="photo-hover-overlay" />
        </motion.div>
      ))}
      <style>{`.photo-card:hover .photo-hover-overlay { opacity: 1 !important; }`}</style>
    </div>
  );
}
