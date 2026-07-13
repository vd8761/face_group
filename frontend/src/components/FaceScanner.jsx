import { useRef, useState, useCallback } from 'react';
import Webcam from 'react-webcam';
import { motion, AnimatePresence } from 'framer-motion';
import { Camera, Upload, RefreshCw, Loader2 } from 'lucide-react';

export default function FaceScanner({ onCapture, loading }) {
  const [mode, setMode] = useState('webcam'); // 'webcam' | 'file'
  const [capturedImage, setCapturedImage] = useState(null);
  const [cameraReady, setCameraReady] = useState(false);
  const webcamRef = useRef(null);
  const fileRef = useRef(null);

  const capture = useCallback(() => {
    const imageSrc = webcamRef.current?.getScreenshot();
    if (imageSrc) {
      setCapturedImage(imageSrc);
    }
  }, []);

  const retake = () => setCapturedImage(null);

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    setCapturedImage(url);
  };

  const handleScan = async () => {
    if (!capturedImage) return;
    // Convert to File/Blob for upload
    const res = await fetch(capturedImage);
    const blob = await res.blob();
    const file = new File([blob], 'selfie.jpg', { type: 'image/jpeg' });
    onCapture(file);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* Mode toggle */}
      <div style={{
        display: 'flex', background: 'var(--color-surface-2)',
        borderRadius: 'var(--radius-md)', padding: '4px', width: 'fit-content', gap: '4px',
      }}>
        {[
          { id: 'webcam', label: 'Use Camera', icon: Camera },
          { id: 'file',   label: 'Upload Photo', icon: Upload },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => { setMode(id); setCapturedImage(null); }}
            className="btn btn-sm"
            style={{
              background: mode === id ? 'var(--accent-soft)' : 'transparent',
              color: mode === id ? 'var(--accent-light)' : 'var(--text-muted)',
              border: mode === id ? '1px solid rgba(124,58,237,0.3)' : '1px solid transparent',
            }}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {/* Camera / preview */}
      <div className="webcam-wrap">
        <AnimatePresence mode="wait">
          {capturedImage ? (
            <motion.img
              key="preview"
              src={capturedImage}
              alt="Captured selfie"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />
          ) : mode === 'webcam' ? (
            <motion.div key="webcam" initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ width: '100%', height: '100%' }}>
              <Webcam
                ref={webcamRef}
                screenshotFormat="image/jpeg"
                videoConstraints={{ facingMode: 'user', width: 640, height: 480 }}
                mirrored={true}
                onUserMedia={() => setCameraReady(true)}
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
              />
              {cameraReady && (
                <>
                  <div className="scan-line" />
                  <div className="scan-corners" />
                </>
              )}
            </motion.div>
          ) : (
            <motion.div
              key="file-drop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              style={{
                width: '100%', height: '100%',
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                gap: '1rem', cursor: 'pointer',
              }}
              onClick={() => fileRef.current?.click()}
            >
              <Upload size={40} color="var(--accent-light)" />
              <p className="text-sm text-secondary">Click to select a photo of your face</p>
              <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleFile} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Action buttons */}
      <div className="flex gap-3">
        {!capturedImage ? (
          mode === 'webcam' ? (
            <button
              className="btn btn-primary w-full"
              onClick={capture}
              disabled={!cameraReady}
            >
              <Camera size={16} /> Take Photo
            </button>
          ) : null
        ) : (
          <>
            <button className="btn btn-ghost" onClick={retake}>
              <RefreshCw size={15} /> Retake
            </button>
            <button
              className="btn btn-primary w-full"
              onClick={handleScan}
              disabled={loading}
            >
              {loading
                ? <><Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> Scanning…</>
                : '🔍 Find My Photos'}
            </button>
          </>
        )}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
