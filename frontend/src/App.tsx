import React from 'react'
import { ConfigProvider } from 'tdesign-react'
import 'tdesign-react/es/style/index.css'
import './index.css'
import TranslationWorkbenchPage from './pages/TranslationWorkbenchPage'

const App: React.FC = () => {
  return (
    <ConfigProvider globalConfig={{}}>
      <TranslationWorkbenchPage />
    </ConfigProvider>
  )
}

export default App
