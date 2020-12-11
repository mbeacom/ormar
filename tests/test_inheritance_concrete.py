# type: ignore
import datetime
from typing import Optional

import databases
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine

import ormar
from ormar import ModelDefinitionError
from tests.settings import DATABASE_URL

metadata = sa.MetaData()
db = databases.Database(DATABASE_URL)
engine = create_engine(DATABASE_URL)


class AuditModel(ormar.Model):
    class Meta:
        abstract = True

    created_by: str = ormar.String(max_length=100)
    updated_by: str = ormar.String(max_length=100, default="Sam")


class DateFieldsModelNoSubclass(ormar.Model):
    class Meta:
        tablename = "test_date_models"
        metadata = metadata
        database = db

    date_id: int = ormar.Integer(primary_key=True)
    created_date: datetime.datetime = ormar.DateTime(default=datetime.datetime.now)
    updated_date: datetime.datetime = ormar.DateTime(default=datetime.datetime.now)


class DateFieldsModel(ormar.Model):
    class Meta:
        abstract = True

    created_date: datetime.datetime = ormar.DateTime(default=datetime.datetime.now)
    updated_date: datetime.datetime = ormar.DateTime(default=datetime.datetime.now)


class Category(DateFieldsModel, AuditModel):
    class Meta(ormar.ModelMeta):
        tablename = "categories"
        metadata = metadata
        database = db

    id: int = ormar.Integer(primary_key=True)
    name: str = ormar.String(max_length=50, unique=True, index=True)
    code: int = ormar.Integer()


class Subject(DateFieldsModel):
    class Meta(ormar.ModelMeta):
        tablename = "subjects"
        metadata = metadata
        database = db

    id: int = ormar.Integer(primary_key=True)
    name: str = ormar.String(max_length=50, unique=True, index=True)
    category: Optional[Category] = ormar.ForeignKey(Category)


@pytest.fixture(autouse=True, scope="module")
def create_test_database():
    metadata.create_all(engine)
    yield
    metadata.drop_all(engine)


def test_field_redefining_raises_error():
    with pytest.raises(ModelDefinitionError):
        class WrongField(DateFieldsModel):  # pragma: no cover
            class Meta(ormar.ModelMeta):
                tablename = "wrongs"
                metadata = metadata
                database = db

            id: int = ormar.Integer(primary_key=True)
            created_date: datetime.datetime = ormar.DateTime()


def test_model_subclassing_non_abstract_raises_error():
    with pytest.raises(ModelDefinitionError):
        class WrongField2(DateFieldsModelNoSubclass):  # pragma: no cover
            class Meta(ormar.ModelMeta):
                tablename = "wrongs"
                metadata = metadata
                database = db

            id: int = ormar.Integer(primary_key=True)


def round_date_to_seconds(
        date: datetime.datetime,
) -> datetime.datetime:  # pragma: no cover
    if date.microsecond >= 500000:
        date = date + datetime.timedelta(seconds=1)
    return date.replace(microsecond=0)


@pytest.mark.asyncio
async def test_fields_inherited_from_mixin():
    async with db:
        async with db.transaction(force_rollback=True):
            cat = await Category(
                name="Foo", code=123, created_by="Sam", updated_by="Max"
            ).save()
            sub = await Subject(name="Bar", category=cat).save()
            mixin_columns = ["created_date", "updated_date"]
            mixin2_columns = ["created_by", "updated_by"]
            assert all(field in Category.Meta.model_fields for field in mixin_columns)
            assert cat.created_date is not None
            assert cat.updated_date is not None
            assert all(field in Subject.Meta.model_fields for field in mixin_columns)
            assert sub.created_date is not None
            assert sub.updated_date is not None

            assert all(field in Category.Meta.model_fields for field in mixin2_columns)
            assert all(
                field not in Subject.Meta.model_fields for field in mixin2_columns
            )

            inspector = sa.inspect(engine)
            assert "categories" in inspector.get_table_names()
            table_columns = [x.get("name") for x in inspector.get_columns("categories")]
            assert all(col in table_columns for col in mixin_columns)  # + mixin2_columns)

            assert "subjects" in inspector.get_table_names()
            table_columns = [x.get("name") for x in inspector.get_columns("subjects")]
            assert all(col in table_columns for col in mixin_columns)

            sub2 = (
                await Subject.objects.select_related("category")
                    .order_by("-created_date")
                    .exclude_fields("updated_date")
                    .get()
            )
            assert round_date_to_seconds(sub2.created_date) == round_date_to_seconds(
                sub.created_date
            )
            assert sub2.category.updated_date is not None
            assert round_date_to_seconds(
                sub2.category.created_date
            ) == round_date_to_seconds(cat.created_date)
            assert sub2.updated_date is None
            assert sub2.category.created_by == "Sam"
            assert sub2.category.updated_by == cat.updated_by
