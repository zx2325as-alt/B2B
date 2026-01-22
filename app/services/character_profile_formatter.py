from typing import Any, Dict
from app.core.config import settings

class CharacterProfileFormatter:
    """
    负责将 Character 对象格式化为适合 LLM 理解的纯文本描述。
    """

    def __init__(self):
        self.config = settings.PROMPTS.get("character_formatter", {})
        self.template = self.config.get("template", "")
        self.defaults = self.config.get("defaults", {
            "unknown": "未知",
            "no_habits": "- (暂无特定行为习惯)",
            "no_catchphrases": "- (暂无特定口头禅)"
        })

    def format(self, character: Any) -> str:
        """
        将角色的 JSON 属性格式化成一段连贯、清晰的描述性文本。
        """
        attrs = character.attributes or {}
        profile = character.dynamic_profile or {}
        traits = character.traits or {}
        
        unknown_text = self.defaults.get("unknown", "未知")

        # 提取关键字段
        personality = profile.get('personality') or traits.get('personality', unknown_text)
        tone = profile.get('tone') or traits.get('tone', unknown_text)
        background = profile.get('background') or traits.get('background', unknown_text)
        weakness = profile.get('weakness') or traits.get('weakness', unknown_text)
        
        behavior_habits = profile.get('behavior_habits') or traits.get('behavior_habits', [])
        catchphrases = profile.get('catchphrase') or traits.get('catchphrase', [])
        
        # 列表处理
        if isinstance(behavior_habits, str): behavior_habits = [behavior_habits]
        if isinstance(catchphrases, str): catchphrases = [catchphrases]

        # 构建 habits 文本
        habits_lines = []
        if behavior_habits:
            for habit in behavior_habits:
                habits_lines.append(f"- {habit}")
        else:
            habits_lines.append(self.defaults.get("no_habits"))
        habits_str = "\n".join(habits_lines)

        # 构建 catchphrases 文本
        catchphrases_lines = []
        if catchphrases:
            for phrase in catchphrases:
                catchphrases_lines.append(f"- 常说：“{phrase}”")
        else:
            catchphrases_lines.append(self.defaults.get("no_catchphrases"))
        catchphrases_str = "\n".join(catchphrases_lines)

        # 如果模板为空（配置加载失败），使用默认硬编码逻辑（这里略去，假设配置存在，或者提供一个简单的fallback）
        if not self.template:
             # Fallback simple format
             return f"Name: {character.name}\nAttributes: {attrs}\nProfile: {profile}"

        return self.template.format(
            name=character.name,
            age=attrs.get('age', unknown_text),
            occupation=attrs.get('occupation', unknown_text),
            role=attrs.get('role', unknown_text),
            personality=personality,
            tone=tone,
            background=background,
            weakness=weakness,
            habits=habits_str,
            catchphrases=catchphrases_str
        )

character_formatter = CharacterProfileFormatter()
