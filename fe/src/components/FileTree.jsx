import { useState, useMemo } from 'react';
import { Folder, FolderOpen, FileCode2 } from 'lucide-react';

function buildTree(paths) {
  const root = { name: 'root', type: 'folder', children: {}, path: '' };
  
  for (const path of paths) {
    const parts = path.split('/');
    let current = root;
    let currentPath = '';
    
    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      
      if (!current.children[part]) {
        current.children[part] = {
          name: part,
          type: i === parts.length - 1 ? 'file' : 'folder',
          path: currentPath,
          children: {}
        };
      }
      current = current.children[part];
    }
  }
  return root;
}

function TreeNode({ node, level }) {
  const [isOpen, setIsOpen] = useState(level < 2); // default open first 2 levels
  const isFolder = node.type === 'folder';
  
  const children = Object.values(node.children).sort((a, b) => {
    // folders first, then alphabetical
    if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  
  return (
    <div style={{ marginLeft: level > 0 ? 12 : 0 }}>
      {node.name !== 'root' && (
        <div 
          style={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: 8, 
            padding: '4px 0',
            cursor: isFolder ? 'pointer' : 'default',
            color: 'var(--text-secondary)',
            fontSize: '0.85rem'
          }}
          onClick={() => isFolder && setIsOpen(!isOpen)}
        >
          {isFolder ? (
            isOpen ? <FolderOpen size={16} color="var(--accent-1)" /> : <Folder size={16} color="var(--accent-1)" />
          ) : (
            <FileCode2 size={16} color="var(--text-muted)" />
          )}
          <span style={{ 
            whiteSpace: 'nowrap', 
            overflow: 'hidden', 
            textOverflow: 'ellipsis',
            color: isFolder ? 'var(--text-primary)' : 'inherit',
            userSelect: 'none'
          }}>
            {node.name}
          </span>
        </div>
      )}
      
      {(isOpen || node.name === 'root') && children.length > 0 && (
        <div style={{ paddingLeft: node.name !== 'root' ? 8 : 0 }}>
          {children.map(child => (
            <TreeNode key={child.path} node={child} level={level + (node.name === 'root' ? 0 : 1)} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function FileTree({ files = [] }) {
  const tree = useMemo(() => buildTree(files), [files]);
  
  if (!files || files.length === 0) return null;
  
  return (
    <div className="file-tree-container" style={{
      background: 'var(--bg-surface)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-md)',
      padding: '12px 16px',
      maxHeight: '340px',
      overflowY: 'auto',
      overflowX: 'hidden',
      marginTop: '16px'
    }}>
      <div style={{ 
        fontSize: '0.75rem', 
        fontWeight: 700, 
        textTransform: 'uppercase', 
        color: 'var(--text-muted)',
        marginBottom: '12px',
        letterSpacing: '0.5px'
      }}>
        Repository Preview
      </div>
      <TreeNode node={tree} level={0} />
    </div>
  );
}
