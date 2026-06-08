from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.tag import Tag


T = TypeVar("T", bound="E964547412Ede512F9534970C8E3971AResponse200Data")


@_attrs_define
class E964547412Ede512F9534970C8E3971AResponse200Data:
    """
    Attributes:
        tag (Union[Unset, Tag]):
    """

    tag: Union[Unset, "Tag"] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tag: Union[Unset, dict[str, Any]] = UNSET
        if not isinstance(self.tag, Unset):
            tag = self.tag.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if tag is not UNSET:
            field_dict["tag"] = tag

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.tag import Tag

        d = dict(src_dict)
        _tag = d.pop("tag", UNSET)
        tag: Union[Unset, Tag]
        if isinstance(_tag, Unset):
            tag = UNSET
        else:
            tag = Tag.from_dict(_tag)

        e964547412_ede_512f9534970c8e3971a_response_200_data = cls(
            tag=tag,
        )

        e964547412_ede_512f9534970c8e3971a_response_200_data.additional_properties = d
        return e964547412_ede_512f9534970c8e3971a_response_200_data

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
