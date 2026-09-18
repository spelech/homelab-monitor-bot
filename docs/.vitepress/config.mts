import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

export default withMermaid(
  defineConfig({
    title: 'MonitorBot',
    description: 'Autonomous Homelab SRE, Self-Healing Watcher & AI Agent Delegation',
    ignoreDeadLinks: true,
    themeConfig: {
      nav: [
        { text: 'Overview', link: '/' },
        { text: 'Architecture', link: '/architecture/overview' },
        { text: 'AI Delegation', link: '/ai/agent-dispatch' },
        { text: 'Reliability', link: '/reliability/notifications' },
        { text: 'Reference', link: '/reference/api' }
      ],
      sidebar: {
        '/architecture/': [
          {
            text: 'Architecture',
            items: [
              { text: 'Overview', link: '/architecture/overview' },
              { text: 'Event Watcher', link: '/architecture/event-watcher' },
              { text: 'SRE Auditor', link: '/architecture/sre-auditor' }
            ]
          }
        ],
        '/ai/': [
          {
            text: 'AI Delegation',
            items: [
              { text: 'Agent Dispatch', link: '/ai/agent-dispatch' },
              { text: 'Memory & Qdrant', link: '/ai/memory-rag' },
              { text: 'Prompt Contract', link: '/ai/prompt-contract' }
            ]
          }
        ],
        '/reliability/': [
          {
            text: 'Reliability',
            items: [
              { text: 'Notifications & Fallback', link: '/reliability/notifications' },
              { text: 'Storage & FUSE Auditor', link: '/reliability/storage-auditor' },
              { text: 'Circuit Breakers', link: '/reliability/circuit-breakers' }
            ]
          }
        ],
        '/reference/': [
          {
            text: 'Reference',
            items: [
              { text: 'REST API', link: '/reference/api' },
              { text: 'FastMCP Server', link: '/reference/mcp' },
              { text: 'Configuration & CLI', link: '/reference/configuration' }
            ]
          }
        ]
      }
    }
  })
)
