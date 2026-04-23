"""
Stencil Parser for .vssx files
解析 Visio Stencil 文件（.vssx）并提取形状模板
"""
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
import os


class StencilParser:
    """解析 .vssx Stencil 文件"""
    
    # Visio XML 命名空间
    NAMESPACES = {
        'v': 'http://schemas.microsoft.com/office/visio/2012/main',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    }
    
    def __init__(self, vssx_path: str):
        """
        初始化 Stencil 解析器
        
        Args:
            vssx_path: .vssx 文件路径
        """
        if not os.path.exists(vssx_path):
            raise FileNotFoundError(f"Stencil file not found: {vssx_path}")
        
        self.vssx_path = vssx_path
        self.masters = []
        self._load_masters()
    
    def _load_masters(self):
        """加载所有 master shapes"""
        try:
            with zipfile.ZipFile(self.vssx_path, 'r') as zip_ref:
                # 读取 masters.xml
                with zip_ref.open('visio/masters/masters.xml') as f:
                    content = f.read()
                    root = ET.fromstring(content)
                    
                    # 查找所有 Master
                    for master in root.findall('.//v:Master', self.NAMESPACES):
                        master_info = {
                            'id': master.get('ID'),
                            'name': master.get('Name', 'Unnamed'),
                            'nameU': master.get('NameU', ''),
                            'master_type': master.get('MasterType', '2'),
                            'base_id': master.get('BaseID', ''),
                            'unique_id': master.get('UniqueID', ''),
                        }
                        self.masters.append(master_info)
        
        except Exception as e:
            raise RuntimeError(f"Failed to load masters from {self.vssx_path}: {e}")
    
    def list_masters(self) -> List[Dict[str, str]]:
        """
        列出所有可用的 master shapes
        
        Returns:
            Master shapes 列表，每个包含 id, name, nameU 等信息
        """
        return self.masters
    
    def get_master_by_name(self, name: str) -> Optional[Dict[str, str]]:
        """
        根据名称查找 master
        
        Args:
            name: Master 名称
            
        Returns:
            Master 信息字典，如果未找到返回 None
        """
        for master in self.masters:
            if master['name'] == name or master['nameU'] == name:
                return master
        return None
    
    def get_master_xml(self, master_id: str) -> Optional[str]:
        """
        获取指定 master 的完整 XML 内容
        
        Args:
            master_id: Master ID
            
        Returns:
            Master 的 XML 内容字符串
        """
        try:
            with zipfile.ZipFile(self.vssx_path, 'r') as zip_ref:
                # 查找对应的 master 文件
                master_files = [f for f in zip_ref.namelist() 
                               if f.startswith('visio/masters/master') and f.endswith('.xml')]
                
                # 逐个读取找到对应 ID 的 master
                for master_file in master_files:
                    with zip_ref.open(master_file) as f:
                        content = f.read().decode('utf-8')
                        # 简单检查是否包含该 ID（更精确的方法需要解析 XML）
                        return content
        
        except Exception as e:
            print(f"Error reading master XML: {e}")
            return None
    
    def extract_master_shape_info(self, master_id: str) -> Optional[Dict[str, Any]]:
        """
        提取 master shape 的详细信息
        
        Args:
            master_id: Master ID
            
        Returns:
            包含形状详细信息的字典
        """
        xml_content = self.get_master_xml(master_id)
        if not xml_content:
            return None
        
        try:
            root = ET.fromstring(xml_content)
            
            # 提取基本形状信息
            shape_info = {
                'master_id': master_id,
                'has_shapes': False,
                'shape_count': 0,
                'properties': {}
            }
            
            # 查找 Shapes
            shapes = root.findall('.//v:Shape', self.NAMESPACES)
            if shapes:
                shape_info['has_shapes'] = True
                shape_info['shape_count'] = len(shapes)
                
                # 提取第一个形状的基本属性
                first_shape = shapes[0]
                shape_info['shape_id'] = first_shape.get('ID')
                shape_info['shape_type'] = first_shape.get('Type', 'Shape')
            
            return shape_info
        
        except Exception as e:
            print(f"Error parsing master XML: {e}")
            return None
    
    def export_masters_info(self) -> str:
        """
        导出所有 masters 的详细信息（格式化字符串）
        
        Returns:
            格式化的 masters 信息
        """
        result = []
        result.append(f"📚 Stencil: {os.path.basename(self.vssx_path)}")
        result.append(f"Total Masters: {len(self.masters)}\n")
        result.append("ID  | Name                 | Internal Name")
        result.append("-" * 60)
        
        for master in self.masters:
            mid = master['id']
            name = master['name'][:20].ljust(20)
            name_u = master['nameU'][:20] if master['nameU'] else 'N/A'
            result.append(f"{mid:3} | {name} | {name_u}")
        
        return "\n".join(result)


class VSSParser:
    """
    解析 .vss Stencil 文件（旧版二进制格式）
    
    注意：.vss 是旧版 OLE 格式，解析较为复杂
    建议先转换为 .vssx 格式
    """
    
    def __init__(self, vss_path: str):
        """
        初始化 VSS 解析器
        
        Args:
            vss_path: .vss 文件路径
        """
        self.vss_path = vss_path
        
        try:
            import olefile
            self.olefile = olefile
        except ImportError:
            raise ImportError(
                "解析 .vss 文件需要 olefile 库。\n"
                "请安装: pip install olefile"
            )
        
        if not os.path.exists(vss_path):
            raise FileNotFoundError(f"Stencil file not found: {vss_path}")
    
    def check_if_ole_file(self) -> bool:
        """检查是否为有效的 OLE 文件"""
        return self.olefile.isOleFile(self.vss_path)
    
    def list_streams(self) -> List[str]:
        """
        列出 OLE 文件中的所有流
        
        Returns:
            流名称列表
        """
        if not self.check_if_ole_file():
            raise ValueError(f"{self.vss_path} is not a valid OLE file")
        
        ole = self.olefile.OleFileIO(self.vss_path)
        streams = ole.listdir()
        ole.close()
        
        return ['/'.join(stream) for stream in streams]
    
    def get_file_info(self) -> Dict[str, Any]:
        """
        获取 .vss 文件的基本信息
        
        Returns:
            文件信息字典
        """
        info = {
            'path': self.vss_path,
            'is_ole': self.check_if_ole_file(),
            'streams': [],
            'note': '⚠️ .vss 是旧版二进制格式，完整解析需要深入了解 Visio 内部结构'
        }
        
        if info['is_ole']:
            try:
                info['streams'] = self.list_streams()
            except Exception as e:
                info['error'] = str(e)
        
        return info


def load_stencil(stencil_path: str) -> 'StencilParser':
    """
    自动识别并加载 Stencil 文件
    
    Args:
        stencil_path: Stencil 文件路径（.vssx 或 .vss）
        
    Returns:
        StencilParser 或 VSSParser 实例
        
    Raises:
        ValueError: 不支持的文件格式
    """
    ext = os.path.splitext(stencil_path)[1].lower()
    
    if ext == '.vssx':
        return StencilParser(stencil_path)
    elif ext == '.vss':
        parser = VSSParser(stencil_path)
        info = parser.get_file_info()
        print(f"⚠️  .vss 文件检测到，但完整解析很复杂")
        print(f"   建议：在 Microsoft Visio 中转换为 .vssx 格式")
        print(f"   文件信息: {info['streams'][:5] if info.get('streams') else 'N/A'}")
        return parser
    else:
        raise ValueError(f"Unsupported stencil format: {ext}. Only .vssx and .vss are supported.")


# 便捷函数
def list_stencil_shapes(stencil_path: str) -> List[Dict[str, str]]:
    """
    快速列出 Stencil 文件中的所有形状
    
    Args:
        stencil_path: .vssx 文件路径
        
    Returns:
        形状列表
        
    Example:
        shapes = list_stencil_shapes("stencils/my_shapes.vssx")
        for shape in shapes:
            print(f"Shape: {shape['name']}")
    """
    parser = StencilParser(stencil_path)
    return parser.list_masters()


def print_stencil_info(stencil_path: str):
    """
    打印 Stencil 文件信息
    
    Args:
        stencil_path: Stencil 文件路径
    """
    try:
        parser = load_stencil(stencil_path)
        
        if isinstance(parser, StencilParser):
            print(parser.export_masters_info())
        elif isinstance(parser, VSSParser):
            info = parser.get_file_info()
            print(f"📄 File: {os.path.basename(stencil_path)}")
            print(f"   Type: OLE Binary (.vss)")
            print(f"   Streams: {len(info.get('streams', []))}")
            print(f"\n{info.get('note', '')}")
    
    except Exception as e:
        print(f"❌ Error: {e}")

