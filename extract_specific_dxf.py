import ezdxf
import os

def extract_text_from_dxf(dxf_file_path):
    """使用用户提供的代码提取DXF文件中的文本"""
    try:
        # 读取DXF文件
        doc = ezdxf.readfile(dxf_file_path)
        
        # 获取模型空间
        msp = doc.modelspace()
        
        # 存储提取的文本
        texts = []
        
        # 遍历所有实体
        for entity in msp:
            # 提取TEXT实体
            if entity.dxftype() == 'TEXT':
                text_content = entity.dxf.text
                if text_content.strip():  # 只保留非空文本
                    texts.append({
                        'type': 'TEXT',
                        'content': text_content,
                        'layer': entity.dxf.layer,
                        'position': (entity.dxf.insert.x, entity.dxf.insert.y)
                    })
            
            # 提取MTEXT实体
            elif entity.dxftype() == 'MTEXT':
                text_content = entity.plain_text()
                if text_content.strip():  # 只保留非空文本
                    texts.append({
                        'type': 'MTEXT',
                        'content': text_content,
                        'layer': entity.dxf.layer,
                        'position': (entity.dxf.insert.x, entity.dxf.insert.y)
                    })
        
        return texts
    
    except Exception as e:
        print(f"读取DXF文件时出错: {e}")
        return []

def main():
    # 指定的DXF文件路径
    dxf_file = r"c:\Users\zhenhe\OneDrive\永盛\翻译\cad code\241217-11+小样图.dxf"
    
    # 检查文件是否存在
    if not os.path.exists(dxf_file):
        print(f"文件不存在: {dxf_file}")
        return
    
    print(f"正在处理文件: {dxf_file}")
    print("="*50)
    
    # 提取文本
    extracted_texts = extract_text_from_dxf(dxf_file)
    
    if extracted_texts:
        print(f"共提取到 {len(extracted_texts)} 条文本:")
        print()
        
        for i, text_info in enumerate(extracted_texts, 1):
            print(f"{i}. [{text_info['type']}] 图层: {text_info['layer']}")
            print(f"   位置: ({text_info['position'][0]:.2f}, {text_info['position'][1]:.2f})")
            print(f"   内容: {text_info['content']}")
            print("-" * 30)
    else:
        print("未提取到任何文本内容")

if __name__ == "__main__":
    main()