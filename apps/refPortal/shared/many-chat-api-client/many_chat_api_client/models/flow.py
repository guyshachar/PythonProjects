from collections.abc import Mapping
from typing import Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="Flow")


@_attrs_define
class Flow:
    """
    Attributes:
        ns (Union[Unset, str]): Automation namespace - unique Automation ID
        name (Union[Unset, str]):
        folder_id (Union[Unset, int]):
    """

    ns: Union[Unset, str] = UNSET
    name: Union[Unset, str] = UNSET
    folder_id: Union[Unset, int] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ns = self.ns

        name = self.name

        folder_id = self.folder_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if ns is not UNSET:
            field_dict["ns"] = ns
        if name is not UNSET:
            field_dict["name"] = name
        if folder_id is not UNSET:
            field_dict["folder_id"] = folder_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        ns = d.pop("ns", UNSET)

        name = d.pop("name", UNSET)

        folder_id = d.pop("folder_id", UNSET)

        flow = cls(
            ns=ns,
            name=name,
            folder_id=folder_id,
        )

        flow.additional_properties = d
        return flow

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
