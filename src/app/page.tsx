'use client'

import { useState, useEffect, useCallback } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'

// Types
interface SMPNode {
  id: string
  structural: {
    id: string
    type: string
    name: string
    file: string
    signature?: string
    position: {
      start_line: number
      end_line: number
    }
    modifiers?: string[]
    docstring?: string
    metrics?: {
      complexity: number
      lines: number
      parameters: number
    }
  }
  semantic?: {
    purpose: string
    keywords: string[]
    confidence: number
    last_enriched: string
  }
  relationships: Record<string, string[]>
  created_at: string
  updated_at: string
}

interface GraphEdge {
  from: string
  to: string
  type: string
  metadata?: Record<string, unknown>
}

interface GraphStats {
  total_nodes: number
  total_relationships: number
  nodes_by_type: Record<string, number>
  relationships_by_type: Record<string, number>
  last_indexed: string
}

interface QueryResult {
  result?: unknown
  error?: {
    code: number
    message: string
  }
}

// Icons
const Icons = {
  Function: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 17H7A5 5 0 0 1 7 7h2" /><path d="M15 7h2a5 5 0 0 1 5 5v0a5 5 0 0 1-5 5h-2" /><line x1="8" x2="16" y1="12" y2="12" />
    </svg>
  ),
  Class: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="18" height="18" x="3" y="3" rx="2" /><path d="M7 7h10" /><path d="M7 12h10" /><path d="M7 17h10" />
    </svg>
  ),
  Interface: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect width="18" height="18" x="3" y="3" rx="2" ry="2" /><line x1="3" x2="21" y1="9" y2="9" /><line x1="9" x2="9" y1="21" y2="9" />
    </svg>
  ),
  Variable: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M8 21h8" /><path d="M12 17V21" /><path d="M7 4h10" /><path d="M17 4v8a5 5 0 0 1-10 0V4" /><path d="M5 9h14" />
    </svg>
  ),
  File: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" /><polyline points="14,2 14,8 20,8" />
    </svg>
  ),
  Search: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" />
    </svg>
  ),
  Play: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  ),
  Upload: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" x2="12" y1="3" y2="15" />
    </svg>
  ),
  RefreshCw: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" /><path d="M16 16h5v5" />
    </svg>
  ),
  GitBranch: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="6" x2="6" y1="3" y2="15" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 0 1-9 9" />
    </svg>
  ),
  Zap: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  ),
  ChevronDown: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m6 9 6 6 6-6" />
    </svg>
  ),
}

// Type icon mapping
const getTypeIcon = (type: string) => {
  switch (type) {
    case 'Function':
    case 'Method':
      return <Icons.Function />
    case 'Class':
      return <Icons.Class />
    case 'Interface':
    case 'Type':
      return <Icons.Interface />
    case 'Variable':
    case 'Property':
      return <Icons.Variable />
    default:
      return <Icons.File />
  }
}

// Type color mapping
const getTypeColor = (type: string): string => {
  switch (type) {
    case 'Function':
    case 'Method':
      return 'bg-blue-500/10 text-blue-600 border-blue-500/20'
    case 'Class':
      return 'bg-purple-500/10 text-purple-600 border-purple-500/20'
    case 'Interface':
    case 'Type':
      return 'bg-cyan-500/10 text-cyan-600 border-cyan-500/20'
    case 'Variable':
    case 'Property':
      return 'bg-green-500/10 text-green-600 border-green-500/20'
    case 'File':
      return 'bg-gray-500/10 text-gray-600 border-gray-500/20'
    case 'Test':
      return 'bg-orange-500/10 text-orange-600 border-orange-500/20'
    default:
      return 'bg-slate-500/10 text-slate-600 border-slate-500/20'
  }
}

export default function Home() {
  const [stats, setStats] = useState<GraphStats | null>(null)
  const [nodes, setNodes] = useState<SMPNode[]>([])
  const [edges, setEdges] = useState<GraphEdge[]>([])
  const [selectedNode, setSelectedNode] = useState<SMPNode | null>(null)
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null)
  const [codeInput, setCodeInput] = useState('')
  const [filePath, setFilePath] = useState('example.ts')
  const [queryType, setQueryType] = useState('navigate')
  const [queryParams, setQueryParams] = useState('{\n  "entity_name": "authenticateUser"\n}')
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('dashboard')
  const [initialized, setInitialized] = useState(false)

  // Fetch initial data
  const fetchData = useCallback(async () => {
    try {
      // Fetch status
      const statusRes = await fetch('/api/smp')
      const statusData = await statusRes.json()
      if (statusData.result) {
        setStats(statusData.result)
      }

      // Fetch graph
      const graphRes = await fetch('/api/smp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0',
          method: 'smp/graph',
          id: 'graph',
        }),
      })
      const graphData = await graphRes.json()
      if (graphData.result) {
        setNodes(graphData.result.nodes || [])
        setEdges(graphData.result.edges || [])
      }
    } catch (error) {
      console.error('Failed to fetch data:', error)
    }
  }, [])

  // Load sample code
  const handleLoadSampleCode = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/smp/init')
      const data = await res.json()
      if (data.result?.initialized) {
        setInitialized(true)
        fetchData()
      }
    } catch (error) {
      console.error('Failed to load sample code:', error)
    } finally {
      setLoading(false)
    }
  }, [fetchData])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Auto-load sample code on first visit if no data
  useEffect(() => {
    if (!initialized && stats && stats.total_nodes === 0) {
      handleLoadSampleCode()
    }
  }, [stats, initialized, handleLoadSampleCode])

  // Send SMP request
  const sendRequest = async (method: string, params?: Record<string, unknown>) => {
    setLoading(true)
    try {
      const res = await fetch('/api/smp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0',
          method,
          params,
          id: Date.now().toString(),
        }),
      })
      const data = await res.json()
      setQueryResult(data)
      return data
    } catch (error) {
      console.error('Request failed:', error)
      setQueryResult({ error: { code: -1, message: 'Request failed' } })
      return null
    } finally {
      setLoading(false)
    }
  }

  // Upload code
  const handleUploadCode = async () => {
    if (!codeInput.trim()) return
    
    const result = await sendRequest('smp/update', {
      file_path: filePath,
      content: codeInput,
      change_type: 'modified',
    })
    
    if (result?.result?.status === 'success') {
      fetchData()
    }
  }

  // Execute query
  const handleExecuteQuery = async () => {
    try {
      const params = JSON.parse(queryParams)
      await sendRequest(`smp/${queryType}`, params)
    } catch (error) {
      setQueryResult({ error: { code: -1, message: 'Invalid JSON parameters' } })
    }
  }

  // Clear memory
  const handleClear = async () => {
    await sendRequest('smp/clear')
    fetchData()
  }

  // Render JSON result
  const renderJsonResult = (data: unknown): React.ReactNode => {
    if (data === null || data === undefined) return <span className="text-muted-foreground">null</span>
    if (typeof data !== 'object') return <span className="text-foreground">{String(data)}</span>
    
    if (Array.isArray(data)) {
      return (
        <div className="ml-4">
          <span className="text-muted-foreground">[</span>
          {data.map((item, i) => (
            <div key={i} className="ml-4">
              {renderJsonResult(item)}
              {i < data.length - 1 && <span className="text-muted-foreground">,</span>}
            </div>
          ))}
          <span className="text-muted-foreground">]</span>
        </div>
      )
    }
    
    const entries = Object.entries(data as Record<string, unknown>)
    return (
      <div className="ml-4">
        <span className="text-muted-foreground">{'{'}</span>
        {entries.map(([key, value], i) => (
          <div key={key} className="ml-4">
            <span className="text-blue-600">"{key}"</span>
            <span className="text-muted-foreground">: </span>
            {renderJsonResult(value)}
            {i < entries.length - 1 && <span className="text-muted-foreground">,</span>}
          </div>
        ))}
        <span className="text-muted-foreground">{'}'}</span>
      </div>
    )
  }

  // Group nodes by file
  const nodesByFile = nodes.reduce((acc, node) => {
    const file = node.structural.file
    if (!acc[file]) acc[file] = []
    acc[file].push(node)
    return acc
  }, {} as Record<string, SMPNode[]>)

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 to-slate-950">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
                <Icons.GitBranch />
              </div>
              <div>
                <h1 className="text-xl font-bold text-white">Structural Memory Protocol</h1>
                <p className="text-xs text-slate-400">SMP v1.0 - AI Agent Memory System</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {stats && (
                <Badge variant="outline" className="bg-green-500/10 text-green-400 border-green-500/20">
                  <span className="w-2 h-2 rounded-full bg-green-400 mr-2 animate-pulse" />
                  {stats.total_nodes} nodes
                </Badge>
              )}
              <Button size="sm" variant="outline" onClick={handleLoadSampleCode} disabled={loading}>
                <Icons.Upload className="mr-1" />
                Load Sample
              </Button>
              <Button size="sm" variant="outline" onClick={fetchData}>
                <Icons.RefreshCw />
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto px-4 py-6">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-6">
          <TabsList className="bg-slate-800/50 border border-slate-700">
            <TabsTrigger value="dashboard" className="data-[state=active]:bg-slate-700">Dashboard</TabsTrigger>
            <TabsTrigger value="upload" className="data-[state=active]:bg-slate-700">Upload Code</TabsTrigger>
            <TabsTrigger value="query" className="data-[state=active]:bg-slate-700">Query Engine</TabsTrigger>
            <TabsTrigger value="graph" className="data-[state=active]:bg-slate-700">Graph View</TabsTrigger>
            <TabsTrigger value="api" className="data-[state=active]:bg-slate-700">API Reference</TabsTrigger>
          </TabsList>

          {/* Dashboard Tab */}
          <TabsContent value="dashboard" className="space-y-6">
            {/* Stats Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader className="pb-2">
                  <CardDescription className="text-slate-400">Total Nodes</CardDescription>
                  <CardTitle className="text-3xl text-white">{stats?.total_nodes || 0}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex gap-2 flex-wrap">
                    {stats?.nodes_by_type && Object.entries(stats.nodes_by_type).slice(0, 4).map(([type, count]) => (
                      <Badge key={type} variant="secondary" className="text-xs">
                        {type}: {count}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader className="pb-2">
                  <CardDescription className="text-slate-400">Relationships</CardDescription>
                  <CardTitle className="text-3xl text-white">{stats?.total_relationships || 0}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex gap-2 flex-wrap">
                    {stats?.relationships_by_type && Object.entries(stats.relationships_by_type).slice(0, 4).map(([type, count]) => (
                      <Badge key={type} variant="secondary" className="text-xs">
                        {type}: {count}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>

              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader className="pb-2">
                  <CardDescription className="text-slate-400">Files Indexed</CardDescription>
                  <CardTitle className="text-3xl text-white">{Object.keys(nodesByFile).length}</CardTitle>
                </CardHeader>
                <CardContent>
                  <Badge variant="secondary" className="text-xs">
                    Ready for queries
                  </Badge>
                </CardContent>
              </Card>

              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader className="pb-2">
                  <CardDescription className="text-slate-400">Last Indexed</CardDescription>
                  <CardTitle className="text-lg text-white">
                    {stats?.last_indexed ? new Date(stats.last_indexed).toLocaleTimeString() : 'Never'}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <Button size="sm" variant="destructive" onClick={handleClear}>
                    Clear Memory
                  </Button>
                </CardContent>
              </Card>
            </div>

            {/* Nodes List */}
            <Card className="bg-slate-800/50 border-slate-700">
              <CardHeader>
                <CardTitle className="text-white">Indexed Nodes</CardTitle>
                <CardDescription>Browse all nodes in memory</CardDescription>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[400px]">
                  {Object.entries(nodesByFile).map(([file, fileNodes]) => (
                    <Collapsible key={file} className="mb-4">
                      <CollapsibleTrigger className="flex items-center gap-2 w-full p-2 rounded hover:bg-slate-700/50 text-left">
                        <Icons.ChevronDown />
                        <Icons.File />
                        <span className="font-medium text-slate-200">{file}</span>
                        <Badge variant="outline" className="ml-auto">{fileNodes.length}</Badge>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <div className="ml-8 mt-2 space-y-2">
                          {fileNodes.map(node => (
                            <div
                              key={node.id}
                              className="flex items-center gap-3 p-2 rounded hover:bg-slate-700/30 cursor-pointer"
                              onClick={() => setSelectedNode(node)}
                            >
                              <div className={`${getTypeColor(node.structural.type)} p-1.5 rounded`}>
                                {getTypeIcon(node.structural.type)}
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="font-medium text-slate-200 truncate">{node.structural.name}</div>
                                {node.structural.signature && (
                                  <div className="text-xs text-slate-500 truncate font-mono">{node.structural.signature}</div>
                                )}
                              </div>
                              <Badge variant="outline" className="text-xs">{node.structural.type}</Badge>
                            </div>
                          ))}
                        </div>
                      </CollapsibleContent>
                    </Collapsible>
                  ))}
                  {nodes.length === 0 && (
                    <div className="text-center py-8 text-slate-400">
                      No nodes indexed yet. Upload code to get started.
                    </div>
                  )}
                </ScrollArea>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Upload Tab */}
          <TabsContent value="upload" className="space-y-6">
            <Card className="bg-slate-800/50 border-slate-700">
              <CardHeader>
                <CardTitle className="text-white">Upload Code</CardTitle>
                <CardDescription>Paste code to parse and add to structural memory</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex gap-4">
                  <Input
                    value={filePath}
                    onChange={(e) => setFilePath(e.target.value)}
                    placeholder="File path (e.g., src/auth/login.ts)"
                    className="bg-slate-900 border-slate-700 text-white"
                  />
                  <Button onClick={handleUploadCode} disabled={loading}>
                    <Icons.Upload className="mr-2" />
                    Parse & Index
                  </Button>
                </div>
                <Textarea
                  value={codeInput}
                  onChange={(e) => setCodeInput(e.target.value)}
                  placeholder="Paste your TypeScript/JavaScript/Python code here..."
                  className="font-mono text-sm bg-slate-900 border-slate-700 text-white min-h-[400px]"
                />
                
                {queryResult && (
                  <div className="mt-4">
                    <h4 className="text-sm font-medium text-slate-300 mb-2">Result:</h4>
                    <pre className="p-4 rounded-lg bg-slate-900 border border-slate-700 overflow-auto text-xs text-slate-300">
                      {JSON.stringify(queryResult, null, 2)}
                    </pre>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* Query Tab */}
          <TabsContent value="query" className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader>
                  <CardTitle className="text-white">Query Builder</CardTitle>
                  <CardDescription>Execute SMP queries against the memory store</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-3 gap-2">
                    {['navigate', 'trace', 'context', 'impact', 'locate', 'flow'].map(type => (
                      <Button
                        key={type}
                        variant={queryType === type ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => {
                          setQueryType(type)
                          // Set default params for each query type
                          const defaultParams: Record<string, string> = {
                            navigate: '{\n  "entity_name": "authenticateUser"\n}',
                            trace: '{\n  "start_id": "func_authenticateUser_src_auth_login_ts",\n  "relationship_type": "CALLS",\n  "depth": 3\n}',
                            context: '{\n  "file_path": "src/auth/login.ts",\n  "scope": "edit"\n}',
                            impact: '{\n  "entity_id": "func_authenticateUser_src_auth_login_ts",\n  "change_type": "signature_change"\n}',
                            locate: '{\n  "description": "authentication token jwt",\n  "top_k": 5\n}',
                            flow: '{\n  "start": "func_authenticateUser_src_auth_login_ts",\n  "flow_type": "execution"\n}',
                          }
                          setQueryParams(defaultParams[type] || '{}')
                        }}
                        className="text-xs"
                      >
                        {type}
                      </Button>
                    ))}
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium text-slate-300">Parameters (JSON)</label>
                    <Textarea
                      value={queryParams}
                      onChange={(e) => setQueryParams(e.target.value)}
                      className="font-mono text-sm bg-slate-900 border-slate-700 text-white min-h-[150px]"
                    />
                  </div>

                  <Button onClick={handleExecuteQuery} disabled={loading} className="w-full">
                    <Icons.Play className="mr-2" />
                    Execute Query
                  </Button>
                </CardContent>
              </Card>

              <Card className="bg-slate-800/50 border-slate-700">
                <CardHeader>
                  <CardTitle className="text-white">Query Result</CardTitle>
                  <CardDescription>Response from SMP server</CardDescription>
                </CardHeader>
                <CardContent>
                  <ScrollArea className="h-[400px]">
                    {queryResult ? (
                      <div className="font-mono text-sm text-slate-300">
                        {queryResult.error ? (
                          <Alert variant="destructive">
                            <AlertTitle>Error {queryResult.error.code}</AlertTitle>
                            <AlertDescription>{queryResult.error.message}</AlertDescription>
                          </Alert>
                        ) : (
                          <pre>{JSON.stringify(queryResult.result, null, 2)}</pre>
                        )}
                      </div>
                    ) : (
                      <div className="text-center py-8 text-slate-400">
                        Execute a query to see results
                      </div>
                    )}
                  </ScrollArea>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* Graph Tab */}
          <TabsContent value="graph" className="space-y-6">
            <Card className="bg-slate-800/50 border-slate-700">
              <CardHeader>
                <CardTitle className="text-white">Graph Visualization</CardTitle>
                <CardDescription>Visual representation of code structure</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  {/* Node list */}
                  <div className="border border-slate-700 rounded-lg p-4 bg-slate-900/50">
                    <h3 className="font-medium text-slate-200 mb-3">Nodes ({nodes.length})</h3>
                    <ScrollArea className="h-[500px]">
                      {nodes.filter(n => n.structural.type !== 'File').map(node => (
                        <div
                          key={node.id}
                          className={`flex items-center gap-2 p-2 rounded cursor-pointer mb-1 ${
                            selectedNode?.id === node.id ? 'bg-violet-500/20 border border-violet-500/50' : 'hover:bg-slate-700/50'
                          }`}
                          onClick={() => setSelectedNode(node)}
                        >
                          <div className={`${getTypeColor(node.structural.type)} p-1 rounded`}>
                            {getTypeIcon(node.structural.type)}
                          </div>
                          <span className="text-sm text-slate-200 truncate">{node.structural.name}</span>
                        </div>
                      ))}
                    </ScrollArea>
                  </div>

                  {/* Selected node details */}
                  <div className="lg:col-span-2 border border-slate-700 rounded-lg p-4 bg-slate-900/50">
                    {selectedNode ? (
                      <div className="space-y-4">
                        <div className="flex items-center gap-3">
                          <div className={`${getTypeColor(selectedNode.structural.type)} p-2 rounded`}>
                            {getTypeIcon(selectedNode.structural.type)}
                          </div>
                          <div>
                            <h3 className="text-lg font-bold text-white">{selectedNode.structural.name}</h3>
                            <Badge variant="outline">{selectedNode.structural.type}</Badge>
                          </div>
                        </div>

                        <Separator className="bg-slate-700" />

                        <div className="grid grid-cols-2 gap-4">
                          <div>
                            <h4 className="text-sm font-medium text-slate-400 mb-2">Location</h4>
                            <p className="text-sm text-slate-200">{selectedNode.structural.file}</p>
                            <p className="text-xs text-slate-400">
                              Lines {selectedNode.structural.position.start_line} - {selectedNode.structural.position.end_line}
                            </p>
                          </div>
                          
                          {selectedNode.structural.metrics && (
                            <div>
                              <h4 className="text-sm font-medium text-slate-400 mb-2">Metrics</h4>
                              <div className="flex gap-2 flex-wrap">
                                <Badge variant="secondary">Complexity: {selectedNode.structural.metrics.complexity}</Badge>
                                <Badge variant="secondary">Lines: {selectedNode.structural.metrics.lines}</Badge>
                                <Badge variant="secondary">Params: {selectedNode.structural.metrics.parameters}</Badge>
                              </div>
                            </div>
                          )}
                        </div>

                        {selectedNode.structural.signature && (
                          <div>
                            <h4 className="text-sm font-medium text-slate-400 mb-2">Signature</h4>
                            <pre className="text-sm bg-slate-800 p-2 rounded text-slate-200 overflow-x-auto">
                              {selectedNode.structural.signature}
                            </pre>
                          </div>
                        )}

                        {selectedNode.structural.docstring && (
                          <div>
                            <h4 className="text-sm font-medium text-slate-400 mb-2">Documentation</h4>
                            <p className="text-sm text-slate-200">{selectedNode.structural.docstring}</p>
                          </div>
                        )}

                        {selectedNode.semantic && (
                          <div>
                            <h4 className="text-sm font-medium text-slate-400 mb-2">Purpose</h4>
                            <p className="text-sm text-slate-200">{selectedNode.semantic.purpose}</p>
                            <div className="flex gap-1 mt-2 flex-wrap">
                              {selectedNode.semantic.keywords.map(kw => (
                                <Badge key={kw} variant="outline" className="text-xs">{kw}</Badge>
                              ))}
                            </div>
                          </div>
                        )}

                        <div>
                          <h4 className="text-sm font-medium text-slate-400 mb-2">Relationships</h4>
                          <div className="space-y-2">
                            {Object.entries(selectedNode.relationships).map(([type, ids]) => 
                              ids.length > 0 && (
                                <div key={type}>
                                  <span className="text-xs text-slate-500">{type}: </span>
                                  <span className="text-xs text-slate-300">{ids.length} connections</span>
                                </div>
                              )
                            )}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center justify-center h-full text-slate-400">
                        Select a node to view details
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* API Reference Tab */}
          <TabsContent value="api" className="space-y-6">
            <Card className="bg-slate-800/50 border-slate-700">
              <CardHeader>
                <CardTitle className="text-white">API Reference</CardTitle>
                <CardDescription>SMP Protocol Methods</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow className="border-slate-700">
                      <TableHead className="text-slate-300">Method</TableHead>
                      <TableHead className="text-slate-300">Description</TableHead>
                      <TableHead className="text-slate-300">Parameters</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[
                      { method: 'smp/update', desc: 'Index a file', params: 'file_path, content, change_type' },
                      { method: 'smp/batch_update', desc: 'Index multiple files', params: 'changes[]' },
                      { method: 'smp/navigate', desc: 'Find entity by name', params: 'entity_name, include_relationships' },
                      { method: 'smp/trace', desc: 'Follow relationship chain', params: 'start_id, relationship_type, depth' },
                      { method: 'smp/context', desc: 'Get editing context', params: 'file_path, scope' },
                      { method: 'smp/impact', desc: 'Assess change impact', params: 'entity_id, change_type' },
                      { method: 'smp/locate', desc: 'Find by description', params: 'description, top_k' },
                      { method: 'smp/flow', desc: 'Trace execution flow', params: 'start, end, flow_type' },
                      { method: 'smp/graph', desc: 'Get full graph', params: '-' },
                      { method: 'smp/status', desc: 'Get memory status', params: '-' },
                    ].map(row => (
                      <TableRow key={row.method} className="border-slate-700">
                        <TableCell className="font-mono text-violet-400">{row.method}</TableCell>
                        <TableCell className="text-slate-300">{row.desc}</TableCell>
                        <TableCell className="font-mono text-xs text-slate-400">{row.params}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                <div className="mt-6">
                  <h3 className="font-medium text-white mb-3">Example Request</h3>
                  <pre className="bg-slate-900 p-4 rounded-lg text-sm text-slate-300 overflow-x-auto">
{`{
  "jsonrpc": "2.0",
  "method": "smp/navigate",
  "params": {
    "entity_name": "authenticateUser",
    "include_relationships": true
  },
  "id": 1
}`}
                  </pre>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  )
}
