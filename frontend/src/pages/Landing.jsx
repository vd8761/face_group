import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Camera, Zap, Shield, Download, ArrowRight, Users, Image } from 'lucide-react';

const features = [
  { icon: Camera,   title: 'AI Face Grouping',      desc: 'InsightFace detects and groups every face automatically across thousands of photos.' },
  { icon: Zap,      title: 'Instant Self-Match',    desc: 'Attendees scan their face and find every photo they appear in within seconds.' },
  { icon: Shield,   title: 'Privacy First',         desc: 'Only face embeddings stored — never raw images. GDPR & DPDP Act compliant.' },
  { icon: Download, title: 'Bulk ZIP Download',     desc: 'Stream-download all your matched photos as a single ZIP — no memory limits.' },
];

export default function Landing() {
  return (
    <div style={{ flex: 1, background: 'var(--color-bg)', display: 'flex', flexDirection: 'column' }}>
      
      {/* ── Hero Section ── */}
      <section style={{ 
        padding: '3rem 1.5rem 4rem', 
        textAlign: 'center', 
        position: 'relative', 
        zIndex: 1,
        background: 'radial-gradient(ellipse at top, rgba(139, 92, 246, 0.08) 0%, transparent 60%)',
      }}>
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>

          <h1 className="font-display" style={{ 
            maxWidth: 720, margin: '0 auto 1.5rem', 
            fontSize: 'clamp(2.5rem, 6vw, 4rem)',
            fontWeight: 800,
            lineHeight: 1.15,
            letterSpacing: '-0.03em',
            color: 'var(--ink)'
          }}>
            Find Every Photo<br />
            You Appear In
          </h1>

          <p style={{ 
            maxWidth: 600, margin: '0 auto 2.5rem', 
            fontSize: '1.125rem', color: 'var(--text-muted)',
            lineHeight: 1.6
          }}>
            Event organizers upload photos. Attendees scan their face and
            instantly get every picture they're in — as a gallery or a ZIP download.
          </p>

          <div style={{ display: 'flex', justifyContent: 'center', gap: '1.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <Link to="/scan" className="btn btn-primary btn-pill" style={{ padding: '0.875rem 2rem', fontSize: '1rem', boxShadow: '0 8px 24px rgba(91, 95, 239, 0.25)' }}>
              <Camera size={20} /> Find My Photos
            </Link>
            <Link to="/login" className="btn btn-ghost" style={{ padding: '0.875rem 1.5rem', fontSize: '1rem', color: 'var(--text-muted)', fontWeight: 600 }}>
              Organizer Login <ArrowRight size={16} />
            </Link>
          </div>
        </motion.div>

        {/* Floating stat badges */}
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, duration: 0.7 }}
          style={{ display: 'flex', justifyContent: 'center', gap: '1.25rem', marginTop: '5rem', flexWrap: 'wrap' }}
        >
          {[
            { value: '5,000+', label: 'Photos/event' },
            { value: '< 3s',   label: 'Scan to results' },
            { value: '100%',   label: 'Privacy compliant' },
          ].map(({ value, label }) => (
            <div key={label} style={{ 
              background: '#fff', 
              padding: '1.25rem 2.5rem', 
              borderRadius: 'var(--radius-lg)',
              border: '1px solid var(--border-light)',
              boxShadow: '0 4px 20px rgba(0,0,0,0.03)',
              minWidth: 180,
              textAlign: 'center'
            }}>
              <div className="font-display" style={{ fontSize: '1.5rem', fontWeight: 800, letterSpacing: '-0.03em', color: 'var(--ink)' }}>{value}</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 500, marginTop: '0.2rem' }}>{label}</div>
            </div>
          ))}
        </motion.div>
      </section>

      {/* ── Features grid ── */}
      <section style={{ padding: '6rem 1.5rem', background: '#fafafa' }}>
        <div className="container">
          <motion.div
            initial={{ opacity: 0 }} whileInView={{ opacity: 1 }}
            viewport={{ once: true }} transition={{ duration: 0.5 }}
            style={{ textAlign: 'center', marginBottom: '4rem' }}
          >
            <h2 className="font-display" style={{ fontSize: '2rem', fontWeight: 800, marginBottom: '0.75rem', color: 'var(--ink)' }}>How it works</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '1.1rem' }}>
              Built for event organizers. Loved by every attendee.
            </p>
          </motion.div>

          <div style={{ 
            display: 'grid', 
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', 
            gap: '1.5rem', 
            maxWidth: 1000, 
            margin: '0 auto' 
          }}>
            {features.map(({ title, desc }, i) => (
              <motion.div
                key={title}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
                style={{
                  background: '#fff',
                  padding: '2.5rem 2rem',
                  borderRadius: 'var(--radius-xl)',
                  border: '1px solid var(--border-light)',
                  boxShadow: '0 2px 10px rgba(0,0,0,0.01)'
                }}
              >
                <h3 className="font-display" style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '1rem', color: 'var(--ink)' }}>{title}</h3>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem', lineHeight: 1.6, margin: 0 }}>{desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section style={{ padding: '6rem 1.5rem 8rem', textAlign: 'center', background: 'var(--color-bg)' }}>
        <div style={{ 
          maxWidth: 700, margin: '0 auto', textAlign: 'center', padding: '4rem 2rem', 
          background: 'linear-gradient(135deg, rgba(139, 92, 246, 0.08) 0%, rgba(6, 182, 212, 0.05) 100%)', 
          border: '1px solid rgba(139, 92, 246, 0.15)',
          borderRadius: 'var(--radius-2xl)'
        }}>
          <h2 className="font-display" style={{ fontSize: '2rem', fontWeight: 800, marginBottom: '1rem', color: 'var(--ink)' }}>Ready to find your photos?</h2>
          <p style={{ marginBottom: '2.5rem', color: 'var(--text-muted)', fontSize: '1.1rem' }}>Enter your event access code and scan your face.</p>
          <Link to="/scan" className="btn btn-primary btn-pill" style={{ padding: '0.875rem 2rem', fontSize: '1rem' }}>
            <Camera size={20} /> Start Scanning <ArrowRight size={16} />
          </Link>
        </div>
      </section>
    </div>
  );
}
