import { motion } from 'framer-motion'

/**
 * ScoreGauge — SVG ring gauge for score visualization
 * 
 * @param {number} score - Score value (0-100)
 * @param {number} size - Diameter in px (default 80)
 * @param {number} strokeWidth - Ring width (default 6)
 * @param {boolean} showLabel - Show score number inside
 * @param {string} label - Optional label below score
 */
export default function ScoreGauge({
  score = 0,
  size = 80,
  strokeWidth = 6,
  showLabel = true,
  label = null,
}) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const progress = score !== null ? Math.max(0, Math.min(100, score)) / 100 : 0
  const dashOffset = circumference * (1 - progress)

  const getColorObj = (s) => {
    if (s === null) return { color: '#4a5568', glow: 'none', start: '#4a5568', end: '#2d3748' }
    if (s >= 70) return { color: '#00e887', glow: '0 0 16px rgba(0, 232, 135, 0.6)', start: '#00e887', end: '#00b4ff' }
    if (s >= 40) return { color: '#ffd93d', glow: '0 0 16px rgba(255, 217, 61, 0.5)', start: '#ffd93d', end: '#ffa200' }
    return { color: '#ff4757', glow: '0 0 16px rgba(255, 71, 87, 0.6)', start: '#ff4757', end: '#ff6b81' }
  }

  const style = getColorObj(score)
  const gradientId = `gauge-gradient-${style.start.replace('#', '')}-${score || 'null'}`

  return (
    <div className="relative flex items-center justify-center transition-all duration-300 hover:scale-105" style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="transform -rotate-90 drop-shadow-xl"
        style={{ filter: `drop-shadow(${style.glow})` }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={style.start} />
            <stop offset="100%" stopColor={style.end} />
          </linearGradient>
        </defs>
        {/* Background ring */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={strokeWidth}
        />
        {/* Inner subtle glow background */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius - strokeWidth}
          fill="rgba(255,255,255,0.02)"
        />
        {/* Progress ring */}
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={{ strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: dashOffset }}
          transition={{ duration: 1.5, ease: [0.16, 1, 0.3, 1] }}
        />
      </svg>

      {/* Center label */}
      {showLabel && (
        <div className="absolute inset-0 flex flex-col items-center justify-center z-10 pointer-events-none">
          <motion.span
            className="font-bold font-mono tracking-tighter"
            style={{
              fontSize: size * 0.28,
              background: `linear-gradient(135deg, ${style.start}, ${style.end})`,
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              textShadow: style.glow === 'none' ? 'none' : `0 0 20px ${style.start}40`,
              lineHeight: 1,
            }}
            initial={{ opacity: 0, scale: 0.5, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.6, type: 'spring', stiffness: 200 }}
          >
            {score !== null ? Math.round(score) : '—'}
          </motion.span>
          {label && (
            <span
              className="text-gray-400 mt-0.5 uppercase tracking-widest font-semibold"
              style={{ fontSize: Math.max(size * 0.12, 9) }}
            >
              {label}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
