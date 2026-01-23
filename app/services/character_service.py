from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from app.models.sql_models import Character, CharacterVersion, Relationship
from app.models.domain_schemas import CharacterCreate, CharacterUpdate, RelationshipCreate

class CharacterService:
    """
    角色服务 (Character Service)
    
    核心职责:
    1. 角色CRUD: 创建、读取、更新、删除角色。
    2. 版本控制 (Versioning): 每次更新角色属性时，自动保存旧版本快照。
    3. 关系管理 (Relationship Management): 管理角色之间的社交关系图谱。
    """

    def get_character(self, db: Session, character_id: int):
        """根据ID获取角色对象"""
        return db.query(Character).filter(Character.id == character_id).first()

    def get_characters(self, db: Session, skip: int = 0, limit: int = 100):
        """分页获取角色列表"""
        return db.query(Character).offset(skip).limit(limit).all()

    def create_character(self, db: Session, character: CharacterCreate):
        """创建新角色"""
        db_character = Character(**character.dict())
        db.add(db_character)
        db.commit()
        db.refresh(db_character)
        return db_character

    def update_character(self, db: Session, character_id: int, character: CharacterUpdate):
        """
        更新角色信息并创建版本快照。
        
        Args:
            db (Session): 数据库会话
            character_id (int): 目标角色ID
            character (CharacterUpdate): 更新内容
            
        Returns:
            Character: 更新后的角色对象，版本号+1
        """
        db_character = self.get_character(db, character_id)
        if not db_character:
            return None
        
        # 归档当前版本 (Archive current version)
        version_entry = CharacterVersion(
            character_id=db_character.id,
            version=db_character.version,
            attributes_snapshot=db_character.attributes,
            traits_snapshot=db_character.traits,
            change_reason=character.version_note
        )
        db.add(version_entry)
        
        # 更新字段 (Update fields)
        update_data = character.dict(exclude_unset=True, exclude={'version_note'})
        for key, value in update_data.items():
            setattr(db_character, key, value)
        
        db_character.version += 1
        
        db.commit()
        db.refresh(db_character)
        return db_character

    def delete_character(self, db: Session, character_id: int):
        """删除角色及其所有关系"""
        db_character = self.get_character(db, character_id)
        if not db_character:
            return False
        
        # 1. 删除关联关系 (Delete Relationships - Cascading)
        db.query(Relationship).filter(
            (Relationship.source_id == character_id) | (Relationship.target_id == character_id)
        ).delete(synchronize_session=False)
        
        # 2. 删除角色本体 (Delete Character)
        db.delete(db_character)
        db.commit()
        return True

    def create_relationship(self, db: Session, relation: RelationshipCreate):
        """创建角色关系"""
        db_relation = Relationship(**relation.dict())
        db.add(db_relation)
        db.commit()
        db.refresh(db_relation)
        return db_relation

    def get_relationships(self, db: Session, character_id: int):
        """获取某角色的所有关系（作为源或目标）"""
        # Naive implementation, could be optimized
        return db.query(Relationship).filter(
            (Relationship.source_id == character_id) | (Relationship.target_id == character_id)
        ).all()
    
    def get_all_relationships(self, db: Session):
        """获取系统内所有关系"""
        return db.query(Relationship).all()

    def delete_relationship(self, db: Session, relationship_id: int):
        """删除指定关系"""
        db_rel = db.query(Relationship).filter(Relationship.id == relationship_id).first()
        if db_rel:
            db.delete(db_rel)
            db.commit()
            return True
        return False
        
    def update_relationship(self, db: Session, relationship_id: int, details: dict = None, relation_type: str = None, strength: int = None, sentiment: int = None):
        """更新关系详情或类型"""
        db_rel = db.query(Relationship).filter(Relationship.id == relationship_id).first()
        if not db_rel:
            return None
        
        if relation_type:
            db_rel.relation_type = relation_type
        if details is not None:
            db_rel.details = details
        if strength is not None:
            db_rel.strength = strength
        if sentiment is not None:
            db_rel.sentiment = sentiment
            
        db.commit()
        db.refresh(db_rel)
        return db_rel

    def update_relationship_state(self, db: Session, source_name: str, target_name: str, strength_delta: int, sentiment_delta: int):
        """
        Dynamically update relationship strength and sentiment based on names.
        Creates relationship if it doesn't exist.
        """
        # 1. Find characters
        source = db.query(Character).filter(Character.name == source_name).first()
        target = db.query(Character).filter(Character.name == target_name).first()
        
        if not source or not target:
            return None
            
        # 2. Find Relationship
        # Check both directions or just one? Usually relationships are directed graph edges here?
        # Model has source_id and target_id.
        rel = db.query(Relationship).filter(
            Relationship.source_id == source.id,
            Relationship.target_id == target.id
        ).first()
        
        if not rel:
            # Create new if not exists
            rel = Relationship(
                source_id=source.id,
                target_id=target.id,
                relation_type="Unknown",
                strength=5,
                sentiment=0
            )
            db.add(rel)
        
        # 3. Update values
        # Clamp values: Strength 1-10, Sentiment -5 to 5
        if strength_delta:
            new_strength = (rel.strength or 5) + strength_delta
            rel.strength = max(1, min(10, new_strength))
            
        if sentiment_delta:
            new_sentiment = (rel.sentiment or 0) + sentiment_delta
            rel.sentiment = max(-5, min(5, new_sentiment))
            
        rel.last_updated = func.now()
        db.commit()
        db.refresh(rel)
        return rel

character_service = CharacterService()
