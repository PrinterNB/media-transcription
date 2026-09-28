// Renders LLM markdown output (summaries, chat replies) with Tailwind
// styling matching the zinc dark theme.
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

const components: Components = {
  p: ({ children }) => <p className="text-sm leading-6 text-zinc-300">{children}</p>,
  h1: ({ children }) => <h2 className="mb-1 mt-2 text-base font-semibold text-zinc-100">{children}</h2>,
  h2: ({ children }) => <h2 className="mb-1 mt-2 text-base font-semibold text-zinc-100">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-semibold text-zinc-100">{children}</h3>,
  h4: ({ children }) => <h4 className="mt-1 text-sm font-medium text-zinc-200">{children}</h4>,
  h5: ({ children }) => <h5 className="mt-1 text-sm font-medium text-zinc-200">{children}</h5>,
  h6: ({ children }) => <h6 className="mt-1 text-sm font-medium text-zinc-300">{children}</h6>,
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-zinc-300">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5 text-sm leading-6 text-zinc-300">{children}</ol>,
  li: ({ children }) => <li className="text-sm leading-6 text-zinc-300">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-zinc-100">{children}</strong>,
  em: ({ children }) => <em className="italic text-zinc-300">{children}</em>,
  code: ({ className, children }) => {
    // block-level code arrives as a pre > code with a language-* className
    const isBlock = /language-/.test(className ?? '')
    if (isBlock) {
      return <code className="font-mono text-xs text-zinc-200">{children}</code>
    }
    return (
      <code className="rounded bg-zinc-800 px-1 py-0.5 font-mono text-xs text-zinc-200">{children}</code>
    )
  },
  pre: ({ children }) => <pre className="my-2 overflow-x-auto rounded-lg bg-zinc-800 p-3 text-xs">{children}</pre>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-zinc-700 pl-3 text-sm italic leading-6 text-zinc-400">{children}</blockquote>
  ),
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="text-emerald-400 underline hover:text-emerald-300">
      {children}
    </a>
  ),
  hr: () => <hr className="border-zinc-800" />,
  table: ({ children }) => (
    <div className="max-w-full overflow-x-auto">
      <table className="w-full border-collapse text-sm text-zinc-300">
        <tbody>{children}</tbody>
      </table>
    </div>
  ),
  th: ({ children }) => <th className="border border-zinc-700 px-2 py-1 text-left font-semibold text-zinc-100">{children}</th>,
  td: ({ children }) => <td className="border border-zinc-700 px-2 py-1">{children}</td>,
}

export default function Markdown({ content }: { content: string }) {
  return (
    <div className="space-y-2">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
