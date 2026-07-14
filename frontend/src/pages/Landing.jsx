import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { motion, useInView } from 'framer-motion';
import {
  Camera, Zap, Shield, Download, ArrowRight, Users,
  CheckCircle2, Star, Lock, Globe, Clock, Search
} from 'lucide-react';
import Logo from '../components/Logo';

/* ─── Data ──────────────────────────────────────────────────────────────── */
const STATS = [
  { value: '<10s',    label: 'Guest finds their photos' },
  { value: '<5 min',  label: 'Organizer setup for 500 photos' },
  { value: '97%',     label: 'Face matching accuracy' },
  { value: '100%',    label: 'Guest privacy — no raw selfies stored' },
];

const STEPS = [
  {
    num: '01', color: 'var(--teal)', bg: 'var(--teal-soft)',
    title: 'Upload event photos',
    desc: 'Drag-drop any JPEG files. Our system begins grouping faces automatically in minutes — no manual tagging.',
  },
  {
    num: '02', color: 'var(--orange)', bg: 'var(--orange-soft)',
    title: 'Share an access code',
    desc: 'Send an 8-character code (or QR) to guests. No app download. No sign-up required.',
  },
  {
    num: '03', color: 'var(--success)', bg: 'var(--success-soft)',
    title: 'Guests find photos in 10 seconds',
    desc: 'One selfie scan. Every matching photo appears instantly — ready to view & download as ZIP.',
  },
];

const FEATURES = [
  { icon: Users,          color: 'var(--teal)',    title: 'Smart face grouping in minutes',        desc: 'Our system clusters every unique face automatically. What would take days takes minutes.' },
  { icon: Search,       color: 'var(--orange)',  title: 'Guests find photos in under 10 seconds', desc: 'One selfie scan matches a guest to every photo they appear in — no scrolling through 2,000 shots.' },
  { icon: Shield,       color: 'var(--success)', title: 'Mathematical embeddings only',         desc: 'We store face vectors, not selfies. Vectors cannot reconstruct a photo. GDPR & DPDP compliant.' },
  { icon: Download,     color: 'var(--teal)',    title: 'One-click ZIP download',               desc: 'Guests download every matched photo as a single ZIP archive — streamed, no browser limits.' },
  { icon: Users,        color: 'var(--orange)',  title: 'Unlimited guests per event',           desc: 'Whether 50 or 5,000 attendees — everyone gets their photos. No per-guest fees ever.' },
  { icon: Globe,        color: 'var(--success)', title: 'No app install for guests',            desc: 'Fully browser-based. Share a link or QR code — works on any smartphone in any country.' },
];

const COMPARISON = [
  { feature: 'Guest finds their photos',       manual: 'Hours of manual search', drive: '5–10 min browsing', urface: 'Under 10 seconds' },
  { feature: 'Organizer setup for 500 photos', manual: '3–4 hours of tagging',   drive: '30 min uploading',   urface: 'Under 5 minutes' },
  { feature: 'What guests see',                manual: 'Full album exposed',      drive: 'Full album exposed',  urface: 'Only their own photos' },
  { feature: 'Auto face detection',            manual: '✗',                       drive: '✗',                   urface: '✓ Automatic' },
  { feature: 'Bulk guest download',            manual: 'Shared folder',           drive: 'File by file',        urface: 'One-click ZIP' },
];

const TESTIMONIALS = [
  {
    q: 'We had 1,200 guests at our college fest. In past years it took a week to share photos. With UrFace, every guest had theirs within the hour.',
    name: 'Priya M.', role: 'Event Organizer', event: 'College Cultural Fest · 1,200 guests', avatar: 'P', verified: true,
  },
  {
    q: 'My wedding photography clients get photos of themselves instantly at the reception. The "wow" from guests makes UrFace worth every rupee.',
    name: 'Rahul S.', role: 'Wedding Photographer', event: 'Photography Studio · 40+ events', avatar: 'R', verified: true,
  },
  {
    q: 'I was worried about facial recognition privacy. Knowing only math vectors are stored — not my actual selfie — actually makes this more private than a WhatsApp group.',
    name: 'Deepa K.', role: 'Event Attendee', event: 'Corporate Annual Day', avatar: 'D', verified: false,
  },
];

const FAQS = [
  { q: 'Do guests need to create an account?', a: 'No. Guests enter the event code, scan their face in their browser, and see all their photos. Zero sign-ups, zero app downloads.' },
  { q: 'How accurate is the face matching?', a: 'Our system achieves 97%+ accuracy. A clear, well-lit selfie gives the best results.' },
  { q: 'What happens to the selfie photo?', a: 'It is processed to extract a mathematical face vector and then immediately deleted. We never store the raw selfie image.' },
  { q: 'Can I delete all event data after my event?', a: 'Yes — delete all photos, face data, and metadata from the organizer dashboard. Deletion is immediate and permanent.' },
];

/* ─── Shared helpers ─────────────────────────────────────────────────────── */
function SectionLabel({ children }) {
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
      background: 'linear-gradient(135deg, rgba(6,182,212,0.12), rgba(16,185,129,0.08))',
      border: '1px solid rgba(6,182,212,0.25)',
      borderRadius: '9999px', padding: '0.3rem 1rem',
      fontSize: '0.75rem', fontWeight: 700, color: 'var(--teal-dark)',
      letterSpacing: '0.06em', textTransform: 'uppercase',
      marginBottom: '1rem',
    }}>
      {children}
    </div>
  );
}

function CTAButton({ to, children, variant = 'primary', style: s = {} }) {
  return (
    <Link to={to}>
      <button
        className={variant === 'primary' ? 'btn btn-primary btn-lg' : 'btn btn-lg'}
        style={variant !== 'primary' ? {
          background: 'transparent',
          color: 'var(--navy)',
          border: '2px solid #94A3B8', /* Darker border for visibility */
          ...s
        } : s}
        onMouseEnter={e => {
          if (variant !== 'primary') e.currentTarget.style.borderColor = 'var(--teal)';
        }}
        onMouseLeave={e => {
          if (variant !== 'primary') e.currentTarget.style.borderColor = 'var(--border)';
        }}
      >
        {children}
      </button>
    </Link>
  );
}

/* ─── Main Component ─────────────────────────────────────────────────────── */
export default function Landing() {
  return (
    <div style={{ flex: 1, background: 'var(--base)' }}>

      {/* ═══════════════════ 1. HERO ═══════════════════ */}
      <section className="hero-bg" style={{ padding: '3.5rem 1.5rem 4rem', textAlign: 'center', borderBottom: '1px solid var(--border)' }}>
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          style={{ maxWidth: 800, margin: '0 auto' }}
        >
          {/* Headline */}
          <h1 style={{
            fontSize: 'clamp(2.25rem, 5.5vw, 4rem)',
            fontWeight: 900,
            letterSpacing: '-0.03em',
            lineHeight: 1.1,
            color: 'var(--navy)',
            marginBottom: '1.25rem',
          }}>
            Guests find their photos<br />
            <span style={{ background: 'linear-gradient(135deg, #06B6D4, #10B981)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
              in under 10 seconds.
            </span>
          </h1>

          {/* Subheadline */}
          <p style={{ fontSize: '1.15rem', color: 'var(--text-2)', maxWidth: 600, margin: '0 auto 2.5rem', lineHeight: 1.65 }}>
            Upload event photos. Share a code. Every attendee scans their face and instantly gets every picture they appear in — no account, no app, no manual tagging.
          </p>

          {/* CTA row */}
          <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', flexWrap: 'wrap' }}>
            <CTAButton to="/scan">
              <Camera size={18} /> Get Started
            </CTAButton>
            <CTAButton to="#how-it-works" variant="ghost" onClick={(e) => {
              e.preventDefault();
              document.getElementById('how-it-works')?.scrollIntoView({ behavior: 'smooth' });
            }}>
              How it works <ArrowRight size={16} />
            </CTAButton>
          </div>

          {/* Trust note */}
          <p style={{ marginTop: '1.5rem', fontSize: '0.8rem', color: 'var(--text-3)' }}>
            No credit card · Works on any phone · GDPR & DPDP Act compliant
          </p>
        </motion.div>


      </section>

      {/* ═══════════════════ 2. PROOF BAND ═══════════════════ */}
      <section style={{ padding: '3rem 1.5rem', background: '#fff', borderBottom: '1px solid var(--border)' }}>
        <div style={{ maxWidth: 1000, margin: '0 auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '2rem' }}>
          {STATS.map(({ value, label }, i) => (
            <motion.div
              key={label}
              initial={{ opacity: 0, y: 12 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.08 }}
              style={{ textAlign: 'center' }}
            >
              <div style={{
                fontSize: '2.5rem', fontWeight: 800,
                color: 'var(--navy)',
                letterSpacing: '-0.04em', lineHeight: 1,
              }}>{value}</div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-2)', marginTop: '0.375rem', fontWeight: 500 }}>{label}</div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ═══════════════════ 2. HOW IT WORKS ═══════════════════ */}
      <section id="how-it-works" style={{ padding: '5.5rem 1.5rem', background: 'var(--base)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ maxWidth: 1040, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: '3.5rem' }}>
            <SectionLabel>How it works</SectionLabel>
            <h2 style={{ fontFamily: "'Poppins', sans-serif", marginBottom: '0.75rem' }}>Up and running in under 5 minutes</h2>
            <p style={{ maxWidth: 480, margin: '0 auto', fontSize: '1rem' }}>Three steps. Zero technical setup. If you can upload photos, you can run this.</p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>
            {STEPS.map((step, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.12 }}
                style={{
                  background: '#fff',
                  border: '1.5px solid var(--border)',
                  borderRadius: '16px',
                  padding: '2rem',
                  boxShadow: 'var(--shadow-sm)',
                  position: 'relative',
                  overflow: 'hidden',
                }}
              >
                <div style={{
                  position: 'absolute', top: '-10px', right: '1.25rem',
                  fontFamily: "'Poppins', sans-serif",
                  fontSize: '4.5rem', fontWeight: 900,
                  color: step.bg,
                  lineHeight: 1,
                  userSelect: 'none',
                }}>{step.num}</div>
                <div style={{ width: 10, height: 10, borderRadius: '50%', background: step.color, marginBottom: '1.25rem', boxShadow: `0 0 0 4px ${step.bg}` }} />
                <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--navy)', marginBottom: '0.625rem' }}>{step.title}</h3>
                <p style={{ fontSize: '0.9rem', color: 'var(--text-2)', lineHeight: 1.65, margin: 0 }}>{step.desc}</p>
              </motion.div>
            ))}
          </div>

          <div style={{ textAlign: 'center', marginTop: '2.5rem' }}>
            <Link to="/scan" style={{ color: 'var(--teal-dark)', fontWeight: 600, fontSize: '0.9rem', display: 'inline-flex', alignItems: 'center', gap: '0.35rem', textDecoration: 'none' }}>
              View a sample event <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      </section>

      {/* ═══════════════════ 4. FEATURES ═══════════════════ */}
      <section style={{ padding: '5.5rem 1.5rem', background: '#fff', borderBottom: '1px solid var(--border)' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: '3.5rem' }}>
            <SectionLabel>Features</SectionLabel>
            <h2 style={{ fontFamily: "'Poppins', sans-serif", marginBottom: '0.75rem' }}>Everything you need, nothing you don't</h2>
            <p style={{ maxWidth: 460, margin: '0 auto', fontSize: '1rem' }}>Built specifically for events — not adapted from general cloud storage.</p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.25rem' }}>
            {FEATURES.map(({ icon: Icon, color, title, desc }, i) => (
              <motion.div
                key={title}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.07 }}
                className="card card-interactive"
              >
                <div style={{
                  width: 44, height: 44, borderRadius: '12px',
                  background: color === 'var(--teal)' ? 'var(--teal-soft)' : color === 'var(--orange)' ? 'var(--orange-soft)' : 'var(--success-soft)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  marginBottom: '1rem',
                }}>
                  <Icon size={22} color={color} />
                </div>
                <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--navy)', marginBottom: '0.5rem' }}>{title}</h3>
                <p style={{ fontSize: '0.875rem', lineHeight: 1.65, margin: 0 }}>{desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════ 5. TRUST / SECURITY ═══════════════════ */}
      <section style={{ padding: '4rem 1.5rem', background: 'var(--base)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: '2.5rem' }}>
            <SectionLabel>Security</SectionLabel>
            <h2 style={{ fontFamily: "'Poppins', sans-serif", marginBottom: '0.5rem' }}>Privacy by design — not by policy</h2>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '1.25rem' }}>
            {[
              { icon: Lock,         color: 'var(--teal)',    label: 'TLS 1.3 Encryption',    sub: 'All data in transit is encrypted using industry-standard TLS 1.3.' },
              { icon: Shield,       color: 'var(--navy)',    label: 'GDPR Compliant',         sub: 'Right to erasure, data minimisation, and consent controls built in.' },
              { icon: CheckCircle2, color: 'var(--success)', label: 'DPDP Act Ready',         sub: "Aligned with India's Digital Personal Data Protection Act 2023." },
            ].map(({ icon: Icon, color, label, sub }) => (
              <div key={label} style={{ background: '#fff', border: '1px solid var(--border)', borderRadius: '14px', padding: '1.375rem 1.5rem', display: 'flex', gap: '1rem', alignItems: 'flex-start', boxShadow: 'var(--shadow-xs)' }}>
                <div style={{ width: 38, height: 38, borderRadius: '10px', background: color === 'var(--teal)' ? 'var(--teal-soft)' : color === 'var(--success)' ? 'var(--success-soft)' : 'rgba(15,32,68,0.06)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <Icon size={18} color={color} />
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--navy)', marginBottom: '0.25rem' }}>{label}</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-2)', lineHeight: 1.5 }}>{sub}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════ 6. COMPARISON ═══════════════════ */}
      <section style={{ padding: '5.5rem 1.5rem', background: '#fff', borderBottom: '1px solid var(--border)' }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: '3rem' }}>
            <SectionLabel>Comparison</SectionLabel>
            <h2 style={{ fontFamily: "'Poppins', sans-serif", marginBottom: '0.5rem' }}>Why not just use a shared folder?</h2>
            <p style={{ fontSize: '1rem', maxWidth: 400, margin: '0 auto' }}>The honest comparison — by what actually matters.</p>
          </div>

          <div style={{ background: 'var(--base)', border: '1px solid var(--border)', borderRadius: '16px', overflow: 'hidden', boxShadow: 'var(--shadow-sm)' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
                <thead>
                  <tr>
                    {['', 'Manual sharing', 'Cloud drive', 'UrFace'].map((h, i) => (
                      <th key={h} style={{
                        padding: '1rem 1.25rem', textAlign: i === 0 ? 'left' : 'center',
                        fontWeight: 700, fontSize: '0.775rem', textTransform: 'uppercase', letterSpacing: '0.06em',
                        color: i === 3 ? 'var(--teal-dark)' : 'var(--text-2)',
                        borderBottom: '1px solid var(--border)',
                        background: i === 3 ? 'rgba(6,182,212,0.06)' : '#fff',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {COMPARISON.map((row, ri) => (
                    <tr key={ri} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '0.875rem 1.25rem', color: 'var(--navy)', fontWeight: 600 }}>{row.feature}</td>
                      <td style={{ padding: '0.875rem 1.25rem', textAlign: 'center', color: 'var(--text-2)' }}>{row.manual}</td>
                      <td style={{ padding: '0.875rem 1.25rem', textAlign: 'center', color: 'var(--text-2)' }}>{row.drive}</td>
                      <td style={{ padding: '0.875rem 1.25rem', textAlign: 'center', color: 'var(--teal-dark)', fontWeight: 700, background: 'rgba(6,182,212,0.04)' }}>{row.urface}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      {/* ═══════════════════ 7. TESTIMONIALS ═══════════════════ */}
      <section style={{ padding: '5.5rem 1.5rem', background: 'var(--base)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: '3.5rem' }}>
            <SectionLabel>Testimonials</SectionLabel>
            <h2 style={{ fontFamily: "'Poppins', sans-serif" }}>Organizers save hours. Guests love it.</h2>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1.5rem' }}>
            {TESTIMONIALS.map(({ q, name, role, event, avatar, verified }, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 16 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
                className="card"
                style={{ background: '#fff' }}
              >
                <div style={{ display: 'flex', gap: '0.2rem', marginBottom: '1rem' }}>
                  {[...Array(5)].map((_, si) => <Star key={si} size={13} color="#F59E0B" fill="#F59E0B" />)}
                </div>
                <p style={{ fontSize: '0.875rem', lineHeight: 1.75, color: 'var(--text-1)', fontStyle: 'italic', marginBottom: '1.25rem' }}>"{q}"</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: '50%',
                    background: 'linear-gradient(135deg, var(--teal), var(--success))',
                    color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontWeight: 800, fontSize: '0.875rem', flexShrink: 0,
                  }}>{avatar}</div>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                      <span style={{ fontWeight: 700, fontSize: '0.875rem', color: 'var(--navy)' }}>{name}</span>
                      {verified && (
                        <span style={{ background: 'rgba(6,182,212,0.1)', color: 'var(--teal-dark)', fontSize: '0.6rem', fontWeight: 800, padding: '0.1rem 0.4rem', borderRadius: '4px', letterSpacing: '0.06em' }}>VERIFIED</span>
                      )}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-2)', lineHeight: 1.3 }}>{role}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-3)', marginTop: '0.1rem' }}>{event}</div>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════ 8. FAQ ═══════════════════ */}
      <section style={{ padding: '5rem 1.5rem', background: '#fff', borderBottom: '1px solid var(--border)' }}>
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: '3rem' }}>
            <SectionLabel>FAQ</SectionLabel>
            <h2 style={{ fontFamily: "'Poppins', sans-serif" }}>Questions before you start?</h2>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {FAQS.map((faq, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 10 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.07 }}
                className="card"
              >
                <div style={{ fontWeight: 700, color: 'var(--navy)', marginBottom: '0.5rem' }}>{faq.q}</div>
                <p style={{ fontSize: '0.875rem', lineHeight: 1.7, margin: 0 }}>{faq.a}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════ 9. FINAL CTA ═══════════════════ */}
      <section style={{
        padding: '6rem 1.5rem 8rem', textAlign: 'center',
        background: 'linear-gradient(135deg, #0F2044 0%, #1E3A5F 50%, #0F2044 100%)',
        position: 'relative', overflow: 'hidden',
      }}>
        {/* Background glow */}
        <div style={{
          position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
          width: '600px', height: '300px',
          background: 'radial-gradient(ellipse, rgba(6,182,212,0.2) 0%, transparent 70%)',
          pointerEvents: 'none',
        }} />

        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          style={{ position: 'relative', zIndex: 1 }}
        >
          <h2 style={{
            fontSize: 'clamp(1.75rem, 4vw, 2.75rem)',
            color: '#fff', marginBottom: '1rem', maxWidth: 600, margin: '0 auto 1rem',
          }}>
            Run your next event with the confidence your guests deserve.
          </h2>
          <p style={{ color: 'rgba(255,255,255,0.65)', fontSize: '1.05rem', maxWidth: 500, margin: '0 auto 2.5rem' }}>
            Start with 30 free photos — no credit card. Guests find their photos in under 10 seconds.
          </p>
          <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', flexWrap: 'wrap' }}>
            <Link to="/scan">
              <button className="btn btn-lg btn-primary">
                <Camera size={18} /> Get Started
              </button>
            </Link>
          </div>
          <p style={{ marginTop: '1.5rem', fontSize: '0.8rem', color: 'rgba(255,255,255,0.4)' }}>
            FIND EVERY FACE. RELIVE EVERY MEMORY.
          </p>
        </motion.div>
      </section>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  );
}
