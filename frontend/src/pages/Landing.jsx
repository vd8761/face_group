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
    <div className="hero-bg" style={{ flex: 1 }}>
      {/* Hero */}
      <section style={{ padding: 'clamp(4rem, 10vw, 8rem) 1.5rem 4rem', textAlign: 'center', position: 'relative', zIndex: 1 }}>
        <motion.div initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
            background: 'rgba(124,58,237,0.1)', border: '1px solid rgba(124,58,237,0.25)',
            borderRadius: '999px', padding: '0.375rem 1rem', marginBottom: '1.5rem',
          }}>
            <Zap size={13} color="var(--accent-light)" />
            <span style={{ fontSize: '0.8125rem', color: 'var(--accent-light)', fontWeight: 600 }}>
              AI-Powered · Event-Ready · Privacy-First
            </span>
          </div>

          <h1 style={{ maxWidth: 720, margin: '0 auto 1.25rem' }}>
            Find <span className="gradient-text">Every Photo</span><br />
            You Appear In
          </h1>

          <p style={{ maxWidth: 560, margin: '0 auto 2.5rem', fontSize: '1.125rem', color: 'var(--text-secondary)' }}>
            Event organizers upload photos. Attendees scan their face and instantly
            get every picture they're in — as a gallery or a ZIP download.
          </p>

          <div className="flex justify-center gap-4" style={{ flexWrap: 'wrap' }}>
            <Link to="/scan" className="btn btn-primary btn-lg">
              <Camera size={20} /> Find My Photos
            </Link>
            <Link to="/login" className="btn btn-ghost btn-lg">
              Organizer Login <ArrowRight size={16} />
            </Link>
          </div>
        </motion.div>

        {/* Floating stat badges */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4, duration: 0.7 }}
          style={{ display: 'flex', justifyContent: 'center', gap: '1rem', marginTop: '3.5rem', flexWrap: 'wrap' }}
        >
          {[
            { icon: Image,  value: '5,000+', label: 'Photos/event' },
            { icon: Users,  value: '< 3s',   label: 'Scan to results' },
            { icon: Shield, value: '100%',   label: 'Privacy compliant' },
          ].map(({ icon: Icon, value, label }) => (
            <div key={label} className="card" style={{ padding: '1rem 1.5rem', display: 'flex', alignItems: 'center', gap: '0.875rem', minWidth: 160 }}>
              <div style={{ width: 38, height: 38, background: 'var(--accent-soft)', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <Icon size={18} color="var(--accent-light)" />
              </div>
              <div>
                <div style={{ fontSize: '1.375rem', fontWeight: 800, letterSpacing: '-0.03em', color: 'var(--text-primary)' }}>{value}</div>
                <div className="text-xs text-muted">{label}</div>
              </div>
            </div>
          ))}
        </motion.div>
      </section>

      {/* Features grid */}
      <section style={{ padding: '4rem 1.5rem', position: 'relative', zIndex: 1 }}>
        <div className="container">
          <motion.div
            initial={{ opacity: 0 }} whileInView={{ opacity: 1 }}
            viewport={{ once: true }} transition={{ duration: 0.5 }}
          >
            <h2 className="text-center" style={{ marginBottom: '0.75rem' }}>How it works</h2>
            <p className="text-center text-secondary" style={{ marginBottom: '3rem' }}>
              Built for event organizers. Loved by every attendee.
            </p>
          </motion.div>

          <div className="grid-2" style={{ gap: '1.25rem', maxWidth: 900, margin: '0 auto' }}>
            {features.map(({ icon: Icon, title, desc }, i) => (
              <motion.div
                key={title}
                className="card card-glow"
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
              >
                <div style={{ width: 48, height: 48, background: 'var(--accent-soft)', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '1rem' }}>
                  <Icon size={22} color="var(--accent-light)" />
                </div>
                <h3 style={{ marginBottom: '0.5rem' }}>{title}</h3>
                <p className="text-sm">{desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section style={{ padding: '4rem 1.5rem 6rem', textAlign: 'center', position: 'relative', zIndex: 1 }}>
        <div className="card" style={{ maxWidth: 600, margin: '0 auto', textAlign: 'center', padding: '3rem 2rem', background: 'rgba(124,58,237,0.06)', borderColor: 'rgba(124,58,237,0.2)' }}>
          <h2 style={{ marginBottom: '0.75rem' }}>Ready to find your photos?</h2>
          <p style={{ marginBottom: '2rem' }}>Enter your event access code and scan your face.</p>
          <Link to="/scan" className="btn btn-primary btn-lg">
            <Camera size={20} /> Start Scanning <ArrowRight size={16} />
          </Link>
        </div>
      </section>
    </div>
  );
}
