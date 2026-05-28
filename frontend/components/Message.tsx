import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function UserMessage({ content }: { content: string }) {
  return (
    <div className="ps-turn ps-turn--user">
      <div className="ps-bubble ps-bubble--user">{content}</div>
    </div>
  );
}

export function AssistantText({ content }: { content: string }) {
  if (!content) return null;
  return (
    <div className="ps-bubble ps-bubble--assistant">
      <div className="ps-prose">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ ...props }) => <a target="_blank" rel="noopener noreferrer" {...props} />,
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
}
