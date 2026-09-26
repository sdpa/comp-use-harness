import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'
import App from './App'
import ComputerPreview, { AgentCursorOverlay } from './components/ComputerPreview'

const query = new URLSearchParams(window.location.search)
const Root = query.get('cursor') === '1' ? AgentCursorOverlay : query.get('computer') === '1' ? ComputerPreview : App

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
