from collections.abc import Mapping
from typing import Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Page")


@_attrs_define
class Page:
    """
    Attributes:
        id (Union[Unset, int]): This is Facebook Page ID
        name (Union[Unset, str]):
        category (Union[Unset, str]):
        avatar_link (Union[Unset, str]):
        username (Union[Unset, str]):
        about (Union[Unset, str]):
        description (Union[Unset, str]):
        is_pro (Union[Unset, bool]):
        timezone (Union[Unset, str]):
    """

    id: Union[Unset, int] = UNSET
    name: Union[Unset, str] = UNSET
    category: Union[Unset, str] = UNSET
    avatar_link: Union[Unset, str] = UNSET
    username: Union[Unset, str] = UNSET
    about: Union[Unset, str] = UNSET
    description: Union[Unset, str] = UNSET
    is_pro: Union[Unset, bool] = UNSET
    timezone: Union[Unset, str] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        category = self.category

        avatar_link = self.avatar_link

        username = self.username

        about = self.about

        description = self.description

        is_pro = self.is_pro

        timezone = self.timezone

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if id is not UNSET:
            field_dict["id"] = id
        if name is not UNSET:
            field_dict["name"] = name
        if category is not UNSET:
            field_dict["category"] = category
        if avatar_link is not UNSET:
            field_dict["avatar_link"] = avatar_link
        if username is not UNSET:
            field_dict["username"] = username
        if about is not UNSET:
            field_dict["about"] = about
        if description is not UNSET:
            field_dict["description"] = description
        if is_pro is not UNSET:
            field_dict["is_pro"] = is_pro
        if timezone is not UNSET:
            field_dict["timezone"] = timezone

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id", UNSET)

        name = d.pop("name", UNSET)

        category = d.pop("category", UNSET)

        avatar_link = d.pop("avatar_link", UNSET)

        username = d.pop("username", UNSET)

        about = d.pop("about", UNSET)

        description = d.pop("description", UNSET)

        is_pro = d.pop("is_pro", UNSET)

        timezone = d.pop("timezone", UNSET)

        page = cls(
            id=id,
            name=name,
            category=category,
            avatar_link=avatar_link,
            username=username,
            about=about,
            description=description,
            is_pro=is_pro,
            timezone=timezone,
        )

        page.additional_properties = d
        return page

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
