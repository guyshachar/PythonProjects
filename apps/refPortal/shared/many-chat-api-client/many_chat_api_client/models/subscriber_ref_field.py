from collections.abc import Mapping
from typing import Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SubscriberRefField")


@_attrs_define
class SubscriberRefField:
    """
    Attributes:
        user_ref (Union[Unset, str]):  Example: -1543835812530302162.
        opted_in (Union[Unset, str]): datetime in W3C format Example: 2018-12-03T11:17:54+00:00.
    """

    user_ref: Union[Unset, str] = UNSET
    opted_in: Union[Unset, str] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        user_ref = self.user_ref

        opted_in = self.opted_in

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if user_ref is not UNSET:
            field_dict["user_ref"] = user_ref
        if opted_in is not UNSET:
            field_dict["opted_in"] = opted_in

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        user_ref = d.pop("user_ref", UNSET)

        opted_in = d.pop("opted_in", UNSET)

        subscriber_ref_field = cls(
            user_ref=user_ref,
            opted_in=opted_in,
        )

        subscriber_ref_field.additional_properties = d
        return subscriber_ref_field

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
