
import logging

logger = logging.getLogger(__name__)

def deep_merge_profile(old_data, new_data):
    """
    递归合并字典和列表。
    - Dict: 递归合并键值。
    - List: 追加新元素并去重 (Set-based deduplication)。
    - Primitive: 仅当新值非空时覆盖。
    """
    if not isinstance(new_data, dict):
        return new_data if new_data else old_data
    
    # 从旧数据的副本开始 (Start with a copy of old data)
    merged = old_data.copy() if isinstance(old_data, dict) else {}
    
    for key, new_val in new_data.items():
        old_val = merged.get(key)
        
        # 如果新值为空，则跳过，保留旧值 (Skip empty new values)
        if not new_val:
            continue
        
        if isinstance(new_val, dict) and isinstance(old_val, dict):
            merged[key] = deep_merge_profile(old_val, new_val)
        elif isinstance(new_val, list) and isinstance(old_val, list):
            # 列表合并策略：追加并去重 (Append & Deduplicate)
            try:
                existing_set = set()
                safe_old_val = []
                
                # 处理旧列表 (Handle old list)
                for item in old_val:
                    try:
                        if item not in existing_set:
                            existing_set.add(item)
                            safe_old_val.append(item)
                    except TypeError:
                        # 遇到不可哈希元素（如dict），直接保留
                        safe_old_val.append(item)
                
                # 处理新列表 (Handle new list)
                for item in new_val:
                    try:
                        if item not in existing_set:
                            safe_old_val.append(item)
                            existing_set.add(item)
                    except TypeError:
                        safe_old_val.append(item)
                
                merged[key] = safe_old_val
            except Exception:
                # 兜底策略：直接拼接
                merged[key] = old_val + new_val
        elif isinstance(new_val, list) and isinstance(old_val, str):
            merged[key] = [old_val] + [v for v in new_val if v != old_val]
        elif isinstance(new_val, str) and isinstance(old_val, list):
            merged[key] = old_val + ([new_val] if new_val not in old_val else [])
        elif isinstance(new_val, str) and isinstance(old_val, str):
            if new_val == old_val:
                merged[key] = old_val
            else:
                merged[key] = [old_val, new_val]
        else:
            merged[key] = new_val
    
    return merged
