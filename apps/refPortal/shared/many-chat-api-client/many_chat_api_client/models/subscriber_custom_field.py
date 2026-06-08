from collections.abc import Mapping
from typing import Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.subscriber_custom_field_type import SubscriberCustomFieldType
from ..types import UNSET, Unset

T = TypeVar("T", bound="SubscriberCustomField")


@_attrs_define
class SubscriberCustomField:
    """
    Attributes:
        id (Union[Unset, int]):
        name (Union[Unset, str]):
        type_ (Union[Unset, SubscriberCustomFieldType]):
        description (Union[Unset, str]):
        value (Union[Unset, Any]): string, integer or boolean Example: 'string', 123, true, '2018-07-18',
            '2018-07-02T07:45:00+03:00'.
    """

    id: Union[Unset, int] = UNSET
    name: Union[Unset, str] = UNSET
    type_: Union[Unset, SubscriberCustomFieldType] = UNSET
    description: Union[Unset, str] = UNSET
    value: Union[Unset, Any] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        name = self.name

        type_: Union[Unset, str] = UNSET
        if not isinstance(self.type_, Unset):
            type_ = self.type_.value

        description = self.description

        value = self.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if id is not UNSET:
            field_dict["id"] = id
        if name is not UNSET:
            field_dict["name"] = name
        if type_ is not UNSET:
            field_dict["type"] = type_
        if description is not UNSET:
            field_dict["description"] = description
        if value is not UNSET:
            field_dict["value"] = value

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id", UNSET)

        name = d.pop("name", UNSET)

        _type_ = d.pop("type", UNSET)
        type_: Union[Unset, SubscriberCustomFieldType]
        if isinstance(_type_, Unset):
            type_ = UNSET
        else:
            type_ = SubscriberCustomFieldType(_type_)

        description = d.pop("description", UNSET)

        value = d.pop("value", UNSET)

        subscriber_custom_field = cls(
            id=id,
            name=name,
            type_=type_,
            description=description,
            value=value,
        )

        subscriber_custom_field.additional_properties = d
        return subscriber_custom_field

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
