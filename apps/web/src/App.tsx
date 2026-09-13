import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { PreviewApp } from '@/features/preview/preview-app'

function App() {
  return (
    <TooltipProvider>
      <PreviewApp />
      <Toaster theme="light" position="bottom-right" closeButton />
    </TooltipProvider>
  )
}

export default App
