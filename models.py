from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql.expression import and_

DATABASE_URL = "sqlite:///./gallery.db"
Base = declarative_base()

class Tag(Base):
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, index=True)

class ItemTag(Base):
    __tablename__ = 'item_tags'
    id = Column(Integer, primary_key=True)
    item_type = Column(String(10))  # 'movie', 'pic', 'embed'
    item_id = Column(Integer)
    tag_id = Column(Integer, ForeignKey('tags.id'))
    
    tag = relationship("Tag")
    
    __table_args__ = (
        UniqueConstraint('item_type', 'item_id', 'tag_id', name='_item_tag_uc'),
    )

class Movie(Base):
    __tablename__ = "movies"
    id = Column(Integer, primary_key=True)
    filename = Column(String)
    filepath = Column(String)
    thumbnail = Column(String)
    title = Column(String)
    
    tag_associations = relationship(
        "ItemTag",
        primaryjoin=lambda: and_(
            Movie.id == ItemTag.item_id,
            ItemTag.item_type == 'movie'
        ),
        foreign_keys="[ItemTag.item_id]",
        viewonly=False
    )
    
    tags = relationship(
        "Tag",
        secondary="item_tags",
        primaryjoin=lambda: and_(
            Movie.id == ItemTag.item_id,
            ItemTag.item_type == 'movie'
        ),
        secondaryjoin="Tag.id == ItemTag.tag_id",
        viewonly=True
    )

class Pic(Base):
    __tablename__ = "pics"
    id = Column(Integer, primary_key=True)
    album = Column(String)
    filename = Column(String)
    filepath = Column(String)
    
    tag_associations = relationship(
        "ItemTag",
        primaryjoin=lambda: and_(
            Pic.id == ItemTag.item_id,
            ItemTag.item_type == 'pic'
        ),
        foreign_keys="[ItemTag.item_id]",
        overlaps="tag_associations"
    )
    
    tags = relationship(
        "Tag",
        secondary="item_tags",
        primaryjoin=lambda: and_(
            Pic.id == ItemTag.item_id,
            ItemTag.item_type == 'pic'
        ),
        secondaryjoin="Tag.id == ItemTag.tag_id",
        viewonly=True
    )

class Embed(Base):
    __tablename__ = "embeds"
    id = Column(Integer, primary_key=True)
    embed_code = Column(Text)
    title = Column(String)
    
    tag_associations = relationship(
        "ItemTag",
        primaryjoin=lambda: and_(
            Embed.id == ItemTag.item_id,
            ItemTag.item_type == 'embed'
        ),
        foreign_keys="[ItemTag.item_id]",
        overlaps="tag_associations"
    )
    
    tags = relationship(
        "Tag",
        secondary="item_tags",
        primaryjoin=lambda: and_(
            Embed.id == ItemTag.item_id,
            ItemTag.item_type == 'embed'
        ),
        secondaryjoin="Tag.id == ItemTag.tag_id",
        viewonly=True
    )

# Vytvoření databázového engine
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Vytvoření tabulek
Base.metadata.create_all(bind=engine)

# Database dependency function
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()