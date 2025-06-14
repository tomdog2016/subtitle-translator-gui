import re
import os
from pathlib import Path
import requests
from typing import List, Dict, Tuple, Optional

class LocalTranslator:
    def __init__(self, base_url: str = "http://localhost:8989", token: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.headers = {"Authorization": token} if token else {}
    
    def translate_text(self, text: str, source_lang: str = 'en', target_lang: str = 'zh') -> str:
        """翻译单条文本"""
        url = f"{self.base_url}/translate"
        payload = {
            "from": source_lang,
            "to": target_lang,
            "text": text
        }
        try:
            response = requests.post(
                url, 
                json=payload, 
                headers=self.headers, 
                timeout=30
            )
            response.raise_for_status()
            return response.json()["result"]
        except Exception as e:
            print(f"翻译失败: {text[:50]}... -> {str(e)}")
            return text
    
    def batch_translate(self, texts: List[str], source_lang: str = 'en', target_lang: str = 'zh') -> List[str]:
        """批量翻译文本列表"""
        if not texts:
            return []
            
        url = f"{self.base_url}/translate/batch"
        payload = {
            "from": source_lang,
            "to": target_lang,
            "texts": texts
        }
        try:
            response = requests.post(
                url, 
                json=payload, 
                headers=self.headers, 
                timeout=30
            )
            response.raise_for_status()
            return response.json()["results"]
        except Exception as e:
            print(f"批量翻译失败: {str(e)}")
            return texts

class ASSProcessor:
    def __init__(self, translator: LocalTranslator):
        self.translator = translator
        self.dialogue_pattern = re.compile(
            r'^Dialogue: (\d+),(\d+:\d+:\d+\.\d+),(\d+:\d+:\d+\.\d+),([^,]*),([^,]*),(\d+),(\d+),(\d+),([^,]*),(.*)$'
        )
    
    def parse_ass_file(self, file_path: str) -> Tuple[List[str], List[Dict]]:
        """解析ASS文件，返回头部信息和对话行"""
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        header = []
        dialogues = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('Dialogue:'):
                match = self.dialogue_pattern.match(line)
                if match:
                    parts = list(match.groups())
                    text = parts[9]
                    # 分离样式标签和实际文本
                    styled_text = self._extract_styled_text(text)
                    dialogues.append({
                        'original': line,
                        'parts': parts,
                        'text': text,
                        'styled_text': styled_text
                    })
            else:
                header.append(line)
        
        return header, dialogues
    
    def _extract_styled_text(self, text: str) -> List[Dict]:
        """提取带样式的文本段"""
        # 这里简单处理，实际可能需要更复杂的解析
        # 移除样式标签，只保留纯文本用于翻译
        clean_text = re.sub(r'\{.*?\}', '', text)
        # 处理换行符
        clean_text = clean_text.replace('\\N', ' ')
        return [{'text': clean_text, 'style': {}}]
    
    def _apply_translation(self, original: str, translation: str) -> str:
        """将翻译应用到原始行，保留样式"""
        # 简单实现：在原文后添加换行和翻译
        return f"{original}\\N{{\\fnSimHei\\fs14\\c&H3CF1F7&}}{translation}"
    
    def translate_ass_file(
        self,
        input_file: str,
        output_file: str,
        source_lang: str = 'en',
        target_lang: str = 'zh',
        batch_size: int = 20
    ) -> None:
        """翻译ASS文件并生成双语字幕"""
        print(f"正在处理文件: {input_file}")
        
        # 解析文件
        header, dialogues = self.parse_ass_file(input_file)
        
        # 提取需要翻译的文本
        texts_to_translate = []
        for d in dialogues:
            # 只翻译非空文本
            clean_text = d['text'].strip()
            if clean_text and not clean_text.startswith('{'):
                texts_to_translate.append(clean_text)
        
        print(f"找到 {len(texts_to_translate)} 条需要翻译的文本")
        
        # 批量翻译
        translated_texts = self.translator.batch_translate(
            texts_to_translate,
            source_lang=source_lang,
            target_lang=target_lang
        )
        
        # 创建翻译映射
        translation_map = dict(zip(texts_to_translate, translated_texts))
        
        # 生成新的对话行
        new_dialogues = []
        for d in dialogues:
            original_text = d['text'].strip()
            if original_text and original_text in translation_map:
                # 添加翻译
                translated = self._apply_translation(
                    d['original'],
                    translation_map[original_text]
                )
                # 更新parts中的文本
                parts = d['parts'].copy()
                parts[9] = translated
                new_line = 'Dialogue:' + ','.join(parts[:9]) + ',' + parts[9]
                new_dialogues.append(new_line)
            else:
                new_dialogues.append(d['original'])
        
        # 写入新文件
        with open(output_file, 'w', encoding='utf-8') as f:
            # 写入头部
            f.write('\n'.join(header) + '\n\n')
            # 写入对话
            f.write('\n'.join(new_dialogues))
        
        print(f"翻译完成！已保存到: {output_file}")

def main():
    # 配置
    input_file = "input.ass"
    output_file = "MasterChef.US.S15E02.1080p.HEVC.x265-MeGusta[EZTVx.to]_track3_zh.ass"
    token = "your_token_here"  # 替换为你的token
    
    # 初始化翻译器
    translator = LocalTranslator(token=token)
    processor = ASSProcessor(translator)
    
    # 开始翻译
    processor.translate_ass_file(
        input_file=input_file,
        output_file=output_file,
        source_lang='en',
        target_lang='zh'
    )

if __name__ == "__main__":
    main()