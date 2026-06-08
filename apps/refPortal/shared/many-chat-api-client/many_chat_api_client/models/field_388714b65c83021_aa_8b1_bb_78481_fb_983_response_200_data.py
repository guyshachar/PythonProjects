from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.bot_field import BotField


T = TypeVar("T", bound="Field388714B65C83021Aa8B1Bb78481Fb983Response200Data")


@_attrs_define
class Field388714B65C83021Aa8B1Bb78481Fb983Response200Data:
    """
    Attributes:
        field (Union[Unset, BotField]):
    """

    field: Union[Unset, "BotField"] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        field: Union[Unset, dict[str, Any]] = UNSET
        if not isinstance(self.field, Unset):
            field = self.field.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if field is not UNSET:
            field_dict["field"] = field

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.bot_field import BotField

        d = dict(src_dict)
        _field = d.pop("field", UNSET)
        field: Union[Unset, BotField]
        if isinstance(_field, Unset):
            field = UNSET
        else:
            field = BotField.from_dict(_field)

        field_388714b65c83021_aa_8b1_bb_78481_fb_983_response_200_data = cls(
            field=field,
        )

        field_388714b65c83021_aa_8b1_bb_78481_fb_983_response_200_data.additional_properties = d
        return field_388714b65c83021_aa_8b1_bb_78481_fb_983_response_200_data

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
