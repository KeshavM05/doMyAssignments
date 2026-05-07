import { useState, useRef, useCallback, useEffect } from 'react'
import Editor from '@monaco-editor/react'

// ── Helpers ────────────────────────────────────────────────────────────────

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'))
  return d.toLocaleString()
}

// ── Upload Zone ────────────────────────────────────────────────────────────

function UploadZone({ files, setFiles }) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)

  const addFiles = useCallback((newFiles) => {
    const extAllowed = ['.pdf', '.docx', '.txt', '.md']
    const filtered = Array.from(newFiles).filter(f => {
      const ext = '.' + f.name.split('.').pop().toLowerCase()
      return extAllowed.includes(ext)
    })
    setFiles(prev => {
      const names = new Set(prev.map(f => f.name))
      return [...prev, ...filtered.filter(f => !names.has(f.name))]
    })
  }, [setFiles])

  const onDrop = useCallback((e) => {
    e.preventDefault()
    setDragging(false)
    addFiles(e.dataTransfer.files)
  }, [addFiles])

  const removeFile = (name) => setFiles(prev => prev.filter(f => f.name !== name))

  return (
    <div className="upload-zone-wrapper">
      <div
        className={`upload-zone ${dragging ? 'dragging' : ''}`}
        onDrop={onDrop}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          style={{ display: 'none' }}
          onChange={e => { addFiles(e.target.files); e.target.value = '' }}
        />
        <div className="upload-icon">📂</div>
        <p className="upload-hint">Drop PDF, DOCX, or TXT files here</p>
        <p className="upload-subhint">or click to browse</p>
      </div>

      {files.length > 0 && (
        <ul className="file-list">
          {files.map(f => (
            <li key={f.name} className="file-item">
              <span className="file-icon">
                {f.name.endsWith('.pdf') ? '📄' : f.name.endsWith('.docx') ? '📝' : '📃'}
              </span>
              <span className="file-name">{f.name}</span>
              <span className="file-size">{formatBytes(f.size)}</span>
              <button className="file-remove" onClick={(e) => { e.stopPropagation(); removeFile(f.name) }}>✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Paste Zone ─────────────────────────────────────────────────────────────

function PasteZone({ pasteText, setPasteText }) {
  return (
    <div className="paste-zone-wrapper">
      <textarea
        className="paste-textarea"
        placeholder="Paste your assignment instructions here...

You can paste:
• Assignment question text
• Problem descriptions
• Rubric details
• Any instructions from OnQ, email, or a document"
        value={pasteText}
        onChange={e => setPasteText(e.target.value)}
        spellCheck={false}
      />
      {pasteText && (
        <div className="paste-meta">
          <span>{pasteText.length.toLocaleString()} characters</span>
          <button className="btn-text-sm" onClick={() => setPasteText('')}>Clear</button>
        </div>
      )}
    </div>
  )
}

// ── Status Badge ───────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const map = {
    pending:    { label: 'Pending',    cls: 'badge-pending' },
    processing: { label: 'Processing', cls: 'badge-processing' },
    done:       { label: 'Done',       cls: 'badge-done' },
    error:      { label: 'Error',      cls: 'badge-error' },
  }
  const { label, cls } = map[status] || { label: status, cls: 'badge-pending' }
  return <span className={`badge ${cls}`}>{label}</span>
}

// ── Jobs Table ─────────────────────────────────────────────────────────────

function JobsTable({ jobs, onDownload }) {
  if (!jobs.length) {
    return <p className="no-jobs">No jobs yet. Upload a file or paste text to get started.</p>
  }

  return (
    <table className="jobs-table">
      <thead>
        <tr>
          <th>Files</th>
          <th>Created</th>
          <th>Status</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map(job => (
          <tr key={job.id}>
            <td className="job-files">{job.files.join(', ')}</td>
            <td className="job-date">{formatDate(job.created_at)}</td>
            <td><StatusBadge status={job.status} /></td>
            <td>
              {job.status === 'done' && (
                <button className="btn-download" onClick={() => onDownload(job.id)}>
                  ⬇ Download .tex
                </button>
              )}
              {job.status === 'error' && (
                <span className="job-error" title={job.error}>Error ⚠</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ── Main App ───────────────────────────────────────────────────────────────

export default function App() {
  const [inputTab, setInputTab] = useState('upload') // 'upload' | 'paste'
  const [files, setFiles] = useState([])
  const [pasteText, setPasteText] = useState('')
  const [latexContent, setLatexContent] = useState('')
  const [generating, setGenerating] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')
  const [jobs, setJobs] = useState([])
  const [activeJobId, setActiveJobId] = useState(null)

  useEffect(() => { fetchJobs() }, [])

  async function fetchJobs() {
    try {
      const res = await fetch('/api/jobs')
      if (res.ok) setJobs(await res.json())
    } catch (_) {}
  }

  async function handleGenerate() {
    const isUpload = inputTab === 'upload'
    if (isUpload && !files.length) { setStatusMsg('Please add at least one file.'); return }
    if (!isUpload && !pasteText.trim()) { setStatusMsg('Please paste some assignment text.'); return }
    if (generating) return

    setGenerating(true)
    setLatexContent('')
    setStatusMsg(isUpload ? 'Uploading files...' : 'Submitting text...')

    try {
      let job_id

      if (isUpload) {
        const formData = new FormData()
        for (const f of files) formData.append('files', f)
        const res = await fetch('/api/upload', { method: 'POST', body: formData })
        if (!res.ok) throw new Error((await res.json()).detail || 'Upload failed')
        ;({ job_id } = await res.json())
      } else {
        const res = await fetch('/api/upload-text', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: pasteText, filename: 'pasted_assignment.txt' }),
        })
        if (!res.ok) throw new Error((await res.json()).detail || 'Text submit failed')
        ;({ job_id } = await res.json())
      }

      setActiveJobId(job_id)
      setStatusMsg('Generating...')

      const genRes = await fetch(`/api/generate/${job_id}`, { method: 'POST' })
      if (!genRes.ok) throw new Error((await genRes.json()).detail || 'Generation failed')

      const reader = genRes.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let accumulated = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const chunk = line.slice(6)
          if (chunk === '[DONE]') {
            setStatusMsg('Done! LaTeX generated.')
            setGenerating(false)
            fetchJobs()
            return
          }
          if (chunk.startsWith('[ERROR]')) throw new Error(chunk.slice(7).trim())
          accumulated += chunk + '\n'
          setLatexContent(accumulated)
        }
      }

      setStatusMsg('Done!')
      setGenerating(false)
      fetchJobs()

    } catch (err) {
      setStatusMsg(`Error: ${err.message}`)
      setGenerating(false)
      fetchJobs()
    }
  }

  function handleDownload(jobId) {
    window.open(`/api/output/${jobId}`, '_blank')
  }

  function handleCopy() {
    if (!latexContent) return
    navigator.clipboard.writeText(latexContent).then(() => {
      setStatusMsg('Copied to clipboard!')
      setTimeout(() => setStatusMsg(''), 2000)
    })
  }

  function handleClear() {
    setLatexContent('')
    setFiles([])
    setPasteText('')
    setActiveJobId(null)
    setStatusMsg('')
  }

  const canGenerate = inputTab === 'upload' ? files.length > 0 : pasteText.trim().length > 0

  return (
    <div className="app">
      <header className="header">
        <h1 className="logo">doMyAssignments</h1>
        <p className="tagline">Vision-powered LaTeX generation via AWS Bedrock</p>
      </header>

      {/* Input section */}
      <section className="section upload-section">
        <div className="tab-bar">
          <button
            className={`tab ${inputTab === 'upload' ? 'tab-active' : ''}`}
            onClick={() => setInputTab('upload')}
          >
            📂 Upload Files
          </button>
          <button
            className={`tab ${inputTab === 'paste' ? 'tab-active' : ''}`}
            onClick={() => setInputTab('paste')}
          >
            📋 Paste Text
          </button>
        </div>

        {inputTab === 'upload' ? (
          <UploadZone files={files} setFiles={setFiles} />
        ) : (
          <PasteZone pasteText={pasteText} setPasteText={setPasteText} />
        )}

        <div className="action-row">
          <button
            className={`btn-generate ${!canGenerate || generating ? 'btn-disabled' : ''}`}
            onClick={handleGenerate}
            disabled={!canGenerate || generating}
          >
            {generating ? <><span className="spinner" /> Generating...</> : '⚡ Generate Assignment'}
          </button>
          {statusMsg && (
            <span className={`status-msg ${statusMsg.startsWith('Error') ? 'status-error' : ''}`}>
              {statusMsg}
            </span>
          )}
        </div>
      </section>

      {/* Editor section */}
      <section className="section editor-section">
        <div className="editor-header">
          <h2 className="section-title">LaTeX Output</h2>
          <div className="editor-actions">
            {latexContent && (
              <>
                <button className="btn-icon" onClick={handleCopy}>📋 Copy</button>
                {activeJobId && jobs.find(j => j.id === activeJobId && j.status === 'done') && (
                  <button className="btn-icon" onClick={() => handleDownload(activeJobId)}>⬇ Download</button>
                )}
                <button className="btn-icon btn-clear" onClick={handleClear}>✕ Clear</button>
              </>
            )}
          </div>
        </div>

        <div className="editor-container">
          {generating && !latexContent && (
            <div className="editor-placeholder">
              <div className="spinner-large" />
              <p>Waiting for Bedrock...</p>
            </div>
          )}
          <Editor
            height="600px"
            defaultLanguage="latex"
            value={latexContent}
            onChange={(val) => setLatexContent(val || '')}
            theme="vs-dark"
            options={{
              fontSize: 13,
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              minimap: { enabled: false },
              wordWrap: 'on',
              scrollBeyondLastLine: false,
              lineNumbers: 'on',
              renderLineHighlight: 'all',
              smoothScrolling: true,
              cursorBlinking: 'smooth',
              padding: { top: 16, bottom: 16 },
            }}
          />
        </div>
      </section>

      {/* Jobs history */}
      <section className="section jobs-section">
        <div className="jobs-header">
          <h2 className="section-title">Job History</h2>
          <button className="btn-icon" onClick={fetchJobs}>🔄 Refresh</button>
        </div>
        <JobsTable jobs={jobs} onDownload={handleDownload} />
      </section>

      <footer className="footer">
        <p>Keshav Mehndiratta · Student ID: 20416565 · Powered by AWS Bedrock</p>
      </footer>
    </div>
  )
}
