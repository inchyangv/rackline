import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AppShell } from '@/components/layout/app-shell'

function App() {
  return (
    <TooltipProvider>
      <AppShell />
      <Toaster position="bottom-right" richColors closeButton />
    </TooltipProvider>
  )
}

export default App
