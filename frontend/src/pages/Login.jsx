import { Hexagon, Github } from 'lucide-react'

export default function Login() {

  return (
    <div className="min-h-screen bg-canvas flex items-center justify-center px-4">
      <div className="w-full max-w-sm">

        {/* Logo */}
        <div className="flex items-center justify-center gap-2.5 mb-8">
          <Hexagon size={28} className="text-accent" strokeWidth={1.5} />
          <span className="text-2xl font-semibold text-fg tracking-tight">Stratum</span>
        </div>

        {/* Card */}
        <div className="bg-canvas-subtle border border-border rounded-xl p-8 shadow-sm">
          <h1 className="text-lg font-semibold text-fg text-center mb-1">
            Sign in to Stratum
          </h1>
          <p className="text-sm text-fg-muted text-center mb-6">
            AI-powered code intelligence for your repositories
          </p>

          <a
            href={import.meta.env.DEV
              ? 'http://localhost:8000/accounts/github/login/'
              : '/accounts/github/login/'
            }
            className="flex items-center justify-center gap-2.5 w-full h-10 rounded-lg
                       bg-fg text-canvas text-sm font-medium
                       hover:bg-fg/90 transition-colors"
          >
            <Github size={17} />
            Continue with GitHub
          </a>

          <p className="text-xs text-fg-muted text-center mt-5 leading-relaxed">
            Your code never leaves your infrastructure.
            <br />
            Stratum only reads repository metadata via GitHub.
          </p>
        </div>

        <p className="text-xs text-fg-muted text-center mt-4">
          Self-hosted · Open source · MIT License
        </p>
      </div>
    </div>
  )
}
