import { lazy, Suspense } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
const PreviewApp = lazy(() =>
  import('@/features/preview/preview-app').then((module) => ({
    default: module.PreviewApp,
  })),
)
const GpuApp = lazy(() =>
  import('@/features/gpu/gpu-app').then((module) => ({
    default: module.GpuApp,
  })),
)

function App() {
  return (
    <TooltipProvider>
      <Suspense
        fallback={
          <div role="status" style={{ padding: 32 }}>
            Loading Rackline…
          </div>
        }
      >
        {window.location.pathname.startsWith('/demo') ||
        (!import.meta.env.VITE_GPU_API_URL &&
          !window.location.pathname.startsWith('/app')) ? (
          <PreviewApp />
        ) : (
          <GpuApp />
        )}
      </Suspense>
      <Toaster theme="light" position="bottom-right" closeButton />
    </TooltipProvider>
  )
}

export default App
