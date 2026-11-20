/**
 * The ClaimSense mark: a shield (insurance, a trust boundary) holding a "C" that ends in a check
 * mark (a decision a person confirms). Gold shield, deep-teal field, white stroke.
 */
export function Logo({ size = 40, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      role="img"
      aria-label="ClaimSense"
      className={className}
    >
      <defs>
        <linearGradient id="cs-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#E3C47A" />
          <stop offset="1" stopColor="#B38A3A" />
        </linearGradient>
      </defs>
      {/* shield */}
      <path
        d="M24 3 L42 9.5 V22.5 C42 33.5 34.6 41.4 24 45 C13.4 41.4 6 33.5 6 22.5 V9.5 Z"
        fill="url(#cs-gold)"
      />
      <path
        d="M24 7.4 L38.4 12.6 V22.6 C38.4 31.6 32.6 38.1 24 41.2 C15.4 38.1 9.6 31.6 9.6 22.6 V12.6 Z"
        fill="#0B2E2A"
      />
      {/* a "C" whose lower end turns into a check mark */}
      <path
        d="M30.6 16.4 A9.2 9.2 0 1 0 22.4 32.2 L26.2 28.2 L33.6 20.6"
        fill="none"
        stroke="#FFFFFF"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
