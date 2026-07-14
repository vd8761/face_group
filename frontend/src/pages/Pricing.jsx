import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Check, Zap, Building2, Camera, ArrowRight, Shield, HelpCircle } from 'lucide-react';

const PLANS = [
  {
    id: 'trial',
    name: 'Starter',
    price: 'Free',
    period: '',
    tag: 'No credit card',
    desc: 'Try the full experience with a single event — no commitment needed.',
    cta: 'Try with 30 free photos',
    ctaTo: '/scan',
    ctaStyle: 'outline',
    icon: Camera,
    iconColor: '#5f6368',
    features: [
      '1 event, up to 30 photos',
      'Guests find photos in under 10 seconds',
      'Unlimited face scans per event',
      'ZIP bulk download for guests',
      'Access code sharing',
      '7-day data retention',
    ],
    notIncluded: ['Custom branding', 'Priority processing', 'Analytics dashboard'],
  },
  {
    id: 'event',
    name: 'Per Event',
    price: '₹999',
    period: '/ event',
    tag: 'Most popular',
    highlighted: true,
    desc: 'For organizers who run events regularly. Pay only for what you use.',
    cta: 'See pricing details',
    ctaTo: '/login',
    ctaStyle: 'primary',
    icon: Zap,
    iconColor: '#0b57d0',
    features: [
      'Up to 5,000 photos per event',
      'Guests find photos in under 10 seconds',
      'Unlimited face scans per event',
      'Guests can download unlimited photos',
      'Priority AI processing (avg. 3 min)',
      'Access code + QR code sharing',
      '90-day data retention',
      'Event analytics dashboard',
    ],
    notIncluded: ['White-label branding', 'Paid guest downloads'],
  },
  {
    id: 'business',
    name: 'Business',
    price: '₹4,999',
    period: '/ month',
    tag: 'Teams & studios',
    desc: 'For photographers and studios running multiple events every month.',
    cta: 'Contact sales',
    ctaTo: '/login',
    ctaStyle: 'outline',
    icon: Building2,
    iconColor: '#188038',
    features: [
      'Unlimited events & photos',
      'Guests find photos in under 10 seconds',
      'Unlimited face scans per event',
      'Guests can download unlimited photos',
      'White-label branding on guest pages',
      'Paid guest download option (you set price)',
      'Priority AI processing',
      '1-year data retention',
      'API access',
      'Dedicated support',
    ],
    notIncluded: [],
  },
];

const COMPARISON = [
  { feature: 'Guest finds their photos',       manual: 'Hours, manual search', drive: '5–10 min browsing', urface: 'Under 10 seconds' },
  { feature: 'Setup time for 500 photos',       manual: '3–4 hours of tagging', drive: '30 min uploading', urface: 'Under 5 minutes' },
  { feature: 'Guest privacy',                    manual: 'Full album exposed', drive: 'Full album exposed', urface: 'Only matched photos shown' },
  { feature: 'Bulk download',                    manual: 'Shared folder link', drive: 'File-by-file', urface: 'One-click ZIP' },
  { feature: 'Faces identified automatically',   manual: '✗', drive: '✗', urface: '✓' },
  { feature: 'Works without a guest account',    manual: '✗', drive: '✓', urface: '✓' },
];

const FAQS = [
  {
    q: 'What happens if I go over my photo limit?',
    a: 'On the Starter plan, processing stops at 30 photos. On Per Event plans, we\'ll notify you before the limit and let you top up at ₹15 per additional 100 photos — no surprise charges.',
  },
  {
    q: 'Can I cancel anytime?',
    a: 'Yes. Business subscriptions can be cancelled before the next billing cycle with no penalty. Per Event credits never expire — they\'re yours to use at your own pace.',
  },
  {
    q: 'Is the guest experience really free for attendees?',
    a: 'Always. Guests scan their face and download their photos at no cost on all plans. Paid guest downloads (Business tier) are an optional revenue feature you can enable — it\'s your choice, not ours.',
  },
  {
    q: 'How secure is the face data?',
    a: 'We store only mathematical face embeddings — never raw selfie images. All data is encrypted in transit (TLS 1.3) and at rest (AES-256). We comply with India\'s DPDP Act and GDPR.',
  },
];

export default function Pricing() {
  return (
    <div style={{ flex: 1, background: 'var(--color-bg)' }}>

      {/* ── Hero ── */}
      <section style={{ padding: '5rem 1.5rem 4rem', textAlign: 'center', background: '#fff', borderBottom: '1px solid var(--border-light)' }}>
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', background: '#e8f0fe', borderRadius: '9999px', padding: '0.35rem 1rem', marginBottom: '1.5rem' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--primary)', fontWeight: 700 }}>Transparent pricing, no surprises</span>
          </div>
          <h1 className="font-display" style={{ fontSize: 'clamp(2rem, 5vw, 3.5rem)', color: 'var(--ink)', marginBottom: '1rem' }}>
            Start free. Scale when you need to.
          </h1>
          <p style={{ fontSize: '1.1rem', color: 'var(--text-muted)', maxWidth: 560, margin: '0 auto' }}>
            Every plan gives guests a world-class photo-finding experience. You pay based on how many events you run — nothing more.
          </p>
        </motion.div>
      </section>

      {/* ── Pricing Tiers ── */}
      <section style={{ padding: '4rem 1.5rem', background: 'var(--color-bg)' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.5rem', alignItems: 'start' }}>
          {PLANS.map((plan, i) => {
            const Icon = plan.icon;
            return (
              <motion.div
                key={plan.id}
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                style={{
                  background: '#fff',
                  border: plan.highlighted ? '2px solid var(--primary)' : '1px solid var(--border-light)',
                  borderRadius: '16px',
                  padding: '2rem',
                  position: 'relative',
                  boxShadow: plan.highlighted
                    ? '0 4px 6px 0 rgba(60,64,67,0.3), 0 8px 24px 0 rgba(11,87,208,0.12)'
                    : 'var(--shadow-sm)',
                  transform: plan.highlighted ? 'scale(1.03)' : 'scale(1)',
                }}
              >
                {plan.tag && (
                  <div style={{
                    position: 'absolute', top: plan.highlighted ? '-14px' : '1.25rem', right: plan.highlighted ? '50%' : '1.5rem',
                    transform: plan.highlighted ? 'translateX(50%)' : 'none',
                    background: plan.highlighted ? 'var(--primary)' : 'var(--surface-2)',
                    color: plan.highlighted ? '#fff' : 'var(--text-muted)',
                    padding: '0.25rem 0.875rem', borderRadius: '9999px',
                    fontSize: '0.75rem', fontWeight: 700, letterSpacing: '0.04em',
                    whiteSpace: 'nowrap',
                  }}>
                    {plan.tag}
                  </div>
                )}

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                  <div style={{ width: 40, height: 40, borderRadius: '10px', background: plan.highlighted ? '#e8f0fe' : '#f1f3f4', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Icon size={20} color={plan.iconColor} />
                  </div>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--ink)' }}>{plan.name}</div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{plan.desc.split('.')[0]}.</div>
                  </div>
                </div>

                <div style={{ marginBottom: '1.5rem' }}>
                  <span style={{ fontSize: '2.5rem', fontWeight: 800, color: 'var(--ink)', fontFamily: "'Plus Jakarta Sans', sans-serif", letterSpacing: '-0.03em' }}>{plan.price}</span>
                  <span style={{ fontSize: '1rem', color: 'var(--text-muted)', marginLeft: '0.25rem' }}>{plan.period}</span>
                </div>

                <Link to={plan.ctaTo}>
                  <button
                    style={{
                      width: '100%', padding: '0.875rem', borderRadius: '8px',
                      fontWeight: 700, fontSize: '0.9rem', cursor: 'pointer',
                      transition: 'all 0.15s ease',
                      background: plan.ctaStyle === 'primary' ? 'var(--primary)' : 'transparent',
                      color: plan.ctaStyle === 'primary' ? '#fff' : 'var(--primary)',
                      border: plan.ctaStyle === 'primary' ? 'none' : '2px solid var(--primary)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.opacity = '0.9'; e.currentTarget.style.transform = 'translateY(-1px)'; }}
                    onMouseLeave={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.transform = 'translateY(0)'; }}
                  >
                    {plan.cta} <ArrowRight size={15} />
                  </button>
                </Link>

                <div style={{ borderTop: '1px solid var(--border-light)', marginTop: '1.5rem', paddingTop: '1.5rem' }}>
                  <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.875rem' }}>What's included</div>
                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '0.625rem' }}>
                    {plan.features.map(f => (
                      <li key={f} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: '0.875rem', color: 'var(--ink)' }}>
                        <Check size={15} color="var(--success)" style={{ flexShrink: 0, marginTop: '2px' }} />
                        {f}
                      </li>
                    ))}
                    {plan.notIncluded.map(f => (
                      <li key={f} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: '0.875rem', color: 'var(--text-muted)', opacity: 0.6 }}>
                        <span style={{ flexShrink: 0, width: 15, textAlign: 'center', marginTop: '1px' }}>—</span>
                        {f}
                      </li>
                    ))}
                  </ul>
                </div>
              </motion.div>
            );
          })}
        </div>
      </section>

      {/* ── Limit & Cancel FAQs ── */}
      <section style={{ padding: '2rem 1.5rem 4rem', background: 'var(--color-bg)' }}>
        <div style={{ maxWidth: 760, margin: '0 auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1.25rem' }}>
          <div style={{ background: '#fff', border: '1px solid var(--border-light)', borderRadius: '12px', padding: '1.5rem', boxShadow: 'var(--shadow-sm)' }}>
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
              <div style={{ width: 32, height: 32, borderRadius: '8px', background: '#fff3cd', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <HelpCircle size={16} color="#ea8600" />
              </div>
              <div>
                <div style={{ fontWeight: 700, color: 'var(--ink)', marginBottom: '0.5rem' }}>What if I go over my limit?</div>
                <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>Processing pauses, you get notified, and you can top up at ₹15 per 100 extra photos — no automatic charges.</div>
              </div>
            </div>
          </div>
          <div style={{ background: '#fff', border: '1px solid var(--border-light)', borderRadius: '12px', padding: '1.5rem', boxShadow: 'var(--shadow-sm)' }}>
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
              <div style={{ width: 32, height: 32, borderRadius: '8px', background: '#e8f5e9', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <Shield size={16} color="var(--success)" />
              </div>
              <div>
                <div style={{ fontWeight: 700, color: 'var(--ink)', marginBottom: '0.5rem' }}>Can I cancel anytime?</div>
                <div style={{ fontSize: '0.875rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>Yes. Cancel before your next billing cycle — no penalties. Per Event credits never expire.</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Comparison Table ── */}
      <section style={{ padding: '4rem 1.5rem', background: '#fff', borderTop: '1px solid var(--border-light)', borderBottom: '1px solid var(--border-light)' }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: '3rem' }}>
            <h2 className="font-display" style={{ fontSize: '2rem', color: 'var(--ink)', marginBottom: '0.5rem' }}>How we compare</h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '1rem' }}>Compared by what actually matters to guests: speed and privacy.</p>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
              <thead>
                <tr>
                  {['', 'Manual sharing', 'Generic cloud drive', 'UrFace AI'].map((h, i) => (
                    <th key={h} style={{
                      padding: '0.875rem 1rem', textAlign: i === 0 ? 'left' : 'center',
                      fontWeight: 700, color: i === 3 ? 'var(--primary)' : 'var(--text-muted)',
                      borderBottom: '2px solid var(--border-light)', fontSize: '0.8rem', textTransform: i === 0 ? 'none' : 'uppercase', letterSpacing: i === 0 ? 'normal' : '0.05em',
                      background: i === 3 ? '#e8f0fe' : 'transparent',
                      borderRadius: i === 3 ? '8px 8px 0 0' : '0',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {COMPARISON.map((row, ri) => (
                  <tr key={ri} style={{ borderBottom: '1px solid var(--border-light)' }}>
                    <td style={{ padding: '0.875rem 1rem', color: 'var(--ink)', fontWeight: 600 }}>{row.feature}</td>
                    <td style={{ padding: '0.875rem 1rem', textAlign: 'center', color: 'var(--text-muted)' }}>{row.manual}</td>
                    <td style={{ padding: '0.875rem 1rem', textAlign: 'center', color: 'var(--text-muted)' }}>{row.drive}</td>
                    <td style={{ padding: '0.875rem 1rem', textAlign: 'center', color: 'var(--primary)', fontWeight: 700, background: '#f0f4ff' }}>{row.urface}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ── Full FAQ ── */}
      <section style={{ padding: '5rem 1.5rem', background: 'var(--color-bg)' }}>
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          <h2 className="font-display" style={{ fontSize: '2rem', textAlign: 'center', color: 'var(--ink)', marginBottom: '3rem' }}>Common questions</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {FAQS.map((faq, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 12 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.08 }}
                style={{ background: '#fff', border: '1px solid var(--border-light)', borderRadius: '12px', padding: '1.5rem', boxShadow: 'var(--shadow-sm)' }}
              >
                <div style={{ fontWeight: 700, color: 'var(--ink)', marginBottom: '0.625rem', fontSize: '0.95rem' }}>{faq.q}</div>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem', lineHeight: 1.7 }}>{faq.a}</div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ── */}
      <section style={{ padding: '5rem 1.5rem 6rem', background: '#fff', borderTop: '1px solid var(--border-light)', textAlign: 'center' }}>
        <h2 className="font-display" style={{ fontSize: '2rem', color: 'var(--ink)', marginBottom: '1rem' }}>Ready to run your first event?</h2>
        <p style={{ color: 'var(--text-muted)', marginBottom: '2.5rem', fontSize: '1.05rem', maxWidth: 480, margin: '0 auto 2.5rem' }}>
          Start with 30 free photos — no card required. Your guests find their photos in under 10 seconds.
        </p>
        <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          <Link to="/scan">
            <button style={{ background: 'var(--primary)', color: '#fff', border: 'none', borderRadius: '8px', padding: '1rem 2rem', fontWeight: 700, fontSize: '1rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              Try with 30 free photos <ArrowRight size={17} />
            </button>
          </Link>
          <Link to="/login">
            <button style={{ background: 'transparent', color: 'var(--primary)', border: '2px solid var(--primary)', borderRadius: '8px', padding: '1rem 2rem', fontWeight: 700, fontSize: '1rem', cursor: 'pointer' }}>
              Organizer sign in
            </button>
          </Link>
        </div>
      </section>
    </div>
  );
}
