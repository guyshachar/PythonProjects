from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, Union, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.subscriber_custom_field import SubscriberCustomField
    from ..models.subscriber_ref_field import SubscriberRefField
    from ..models.tag import Tag


T = TypeVar("T", bound="Subscriber")


@_attrs_define
class Subscriber:
    """
    Attributes:
        id (Union[Unset, str]):
        page_id (Union[Unset, str]): This is Facebook Page ID
        user_refs (Union[Unset, list['SubscriberRefField']]): array with ref of subscriber; can be empty Example: [{
            'user_ref':'-1543835812530302162', 'opted_in':'2018-12-03T11:17:54+00:00' }].
        first_name (Union[Unset, str]):
        last_name (Union[Unset, str]):
        name (Union[Unset, str]):
        gender (Union[Unset, str]):
        profile_pic (Union[Unset, str]):
        locale (Union[Unset, str]):
        language (Union[Unset, str]):
        timezone (Union[Unset, str]):
        live_chat_url (Union[Unset, str]):
        last_input_text (Union[Unset, str]):
        optin_phone (Union[Unset, bool]):
        phone (Union[Unset, str]):
        optin_email (Union[Unset, bool]):
        email (Union[Unset, str]):
        subscribed (Union[Unset, str]): datetime in W3C format Example: '2018-07-02T00:00:00+02:00'.
        last_interaction (Union[None, Unset, str]): datetime in W3C format Example: '2018-07-02T00:00:00+02:00'.
        last_seen (Union[Unset, str]): datetime in W3C format Example: '2018-07-02T00:00:00+03:00'.
        is_followup_enabled (Union[Unset, bool]):  Example: True.
        ig_username (Union[Unset, str]):  Example: user_name.
        ig_id (Union[Unset, int]):  Example: 6384638.
        whatsapp_phone (Union[Unset, str]):
        optin_whatsapp (Union[Unset, bool]):  Example: True.
        custom_fields (Union[Unset, list['SubscriberCustomField']]):
        tags (Union[Unset, list['Tag']]):
    """

    id: Union[Unset, str] = UNSET
    page_id: Union[Unset, str] = UNSET
    user_refs: Union[Unset, list["SubscriberRefField"]] = UNSET
    first_name: Union[Unset, str] = UNSET
    last_name: Union[Unset, str] = UNSET
    name: Union[Unset, str] = UNSET
    gender: Union[Unset, str] = UNSET
    profile_pic: Union[Unset, str] = UNSET
    locale: Union[Unset, str] = UNSET
    language: Union[Unset, str] = UNSET
    timezone: Union[Unset, str] = UNSET
    live_chat_url: Union[Unset, str] = UNSET
    last_input_text: Union[Unset, str] = UNSET
    optin_phone: Union[Unset, bool] = UNSET
    phone: Union[Unset, str] = UNSET
    optin_email: Union[Unset, bool] = UNSET
    email: Union[Unset, str] = UNSET
    subscribed: Union[Unset, str] = UNSET
    last_interaction: Union[None, Unset, str] = UNSET
    last_seen: Union[Unset, str] = UNSET
    is_followup_enabled: Union[Unset, bool] = UNSET
    ig_username: Union[Unset, str] = UNSET
    ig_id: Union[Unset, int] = UNSET
    whatsapp_phone: Union[Unset, str] = UNSET
    optin_whatsapp: Union[Unset, bool] = UNSET
    custom_fields: Union[Unset, list["SubscriberCustomField"]] = UNSET
    tags: Union[Unset, list["Tag"]] = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        page_id = self.page_id

        user_refs: Union[Unset, list[dict[str, Any]]] = UNSET
        if not isinstance(self.user_refs, Unset):
            user_refs = []
            for user_refs_item_data in self.user_refs:
                user_refs_item = user_refs_item_data.to_dict()
                user_refs.append(user_refs_item)

        first_name = self.first_name

        last_name = self.last_name

        name = self.name

        gender = self.gender

        profile_pic = self.profile_pic

        locale = self.locale

        language = self.language

        timezone = self.timezone

        live_chat_url = self.live_chat_url

        last_input_text = self.last_input_text

        optin_phone = self.optin_phone

        phone = self.phone

        optin_email = self.optin_email

        email = self.email

        subscribed = self.subscribed

        last_interaction: Union[None, Unset, str]
        if isinstance(self.last_interaction, Unset):
            last_interaction = UNSET
        else:
            last_interaction = self.last_interaction

        last_seen = self.last_seen

        is_followup_enabled = self.is_followup_enabled

        ig_username = self.ig_username

        ig_id = self.ig_id

        whatsapp_phone = self.whatsapp_phone

        optin_whatsapp = self.optin_whatsapp

        custom_fields: Union[Unset, list[dict[str, Any]]] = UNSET
        if not isinstance(self.custom_fields, Unset):
            custom_fields = []
            for custom_fields_item_data in self.custom_fields:
                custom_fields_item = custom_fields_item_data.to_dict()
                custom_fields.append(custom_fields_item)

        tags: Union[Unset, list[dict[str, Any]]] = UNSET
        if not isinstance(self.tags, Unset):
            tags = []
            for tags_item_data in self.tags:
                tags_item = tags_item_data.to_dict()
                tags.append(tags_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if id is not UNSET:
            field_dict["id"] = id
        if page_id is not UNSET:
            field_dict["page_id"] = page_id
        if user_refs is not UNSET:
            field_dict["user_refs"] = user_refs
        if first_name is not UNSET:
            field_dict["first_name"] = first_name
        if last_name is not UNSET:
            field_dict["last_name"] = last_name
        if name is not UNSET:
            field_dict["name"] = name
        if gender is not UNSET:
            field_dict["gender"] = gender
        if profile_pic is not UNSET:
            field_dict["profile_pic"] = profile_pic
        if locale is not UNSET:
            field_dict["locale"] = locale
        if language is not UNSET:
            field_dict["language"] = language
        if timezone is not UNSET:
            field_dict["timezone"] = timezone
        if live_chat_url is not UNSET:
            field_dict["live_chat_url"] = live_chat_url
        if last_input_text is not UNSET:
            field_dict["last_input_text"] = last_input_text
        if optin_phone is not UNSET:
            field_dict["optin_phone"] = optin_phone
        if phone is not UNSET:
            field_dict["phone"] = phone
        if optin_email is not UNSET:
            field_dict["optin_email"] = optin_email
        if email is not UNSET:
            field_dict["email"] = email
        if subscribed is not UNSET:
            field_dict["subscribed"] = subscribed
        if last_interaction is not UNSET:
            field_dict["last_interaction"] = last_interaction
        if last_seen is not UNSET:
            field_dict["last_seen"] = last_seen
        if is_followup_enabled is not UNSET:
            field_dict["is_followup_enabled"] = is_followup_enabled
        if ig_username is not UNSET:
            field_dict["ig_username"] = ig_username
        if ig_id is not UNSET:
            field_dict["ig_id"] = ig_id
        if whatsapp_phone is not UNSET:
            field_dict["whatsapp_phone"] = whatsapp_phone
        if optin_whatsapp is not UNSET:
            field_dict["optin_whatsapp"] = optin_whatsapp
        if custom_fields is not UNSET:
            field_dict["custom_fields"] = custom_fields
        if tags is not UNSET:
            field_dict["tags"] = tags

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.subscriber_custom_field import SubscriberCustomField
        from ..models.subscriber_ref_field import SubscriberRefField
        from ..models.tag import Tag

        d = dict(src_dict)
        id = d.pop("id", UNSET)

        page_id = d.pop("page_id", UNSET)

        user_refs = []
        _user_refs = d.pop("user_refs", UNSET)
        for user_refs_item_data in _user_refs or []:
            user_refs_item = SubscriberRefField.from_dict(user_refs_item_data)

            user_refs.append(user_refs_item)

        first_name = d.pop("first_name", UNSET)

        last_name = d.pop("last_name", UNSET)

        name = d.pop("name", UNSET)

        gender = d.pop("gender", UNSET)

        profile_pic = d.pop("profile_pic", UNSET)

        locale = d.pop("locale", UNSET)

        language = d.pop("language", UNSET)

        timezone = d.pop("timezone", UNSET)

        live_chat_url = d.pop("live_chat_url", UNSET)

        last_input_text = d.pop("last_input_text", UNSET)

        optin_phone = d.pop("optin_phone", UNSET)

        phone = d.pop("phone", UNSET)

        optin_email = d.pop("optin_email", UNSET)

        email = d.pop("email", UNSET)

        subscribed = d.pop("subscribed", UNSET)

        def _parse_last_interaction(data: object) -> Union[None, Unset, str]:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Union[None, Unset, str], data)

        last_interaction = _parse_last_interaction(d.pop("last_interaction", UNSET))

        last_seen = d.pop("last_seen", UNSET)

        is_followup_enabled = d.pop("is_followup_enabled", UNSET)

        ig_username = d.pop("ig_username", UNSET)

        ig_id = d.pop("ig_id", UNSET)

        whatsapp_phone = d.pop("whatsapp_phone", UNSET)

        optin_whatsapp = d.pop("optin_whatsapp", UNSET)

        custom_fields = []
        _custom_fields = d.pop("custom_fields", UNSET)
        for custom_fields_item_data in _custom_fields or []:
            custom_fields_item = SubscriberCustomField.from_dict(custom_fields_item_data)

            custom_fields.append(custom_fields_item)

        tags = []
        _tags = d.pop("tags", UNSET)
        for tags_item_data in _tags or []:
            tags_item = Tag.from_dict(tags_item_data)

            tags.append(tags_item)

        subscriber = cls(
            id=id,
            page_id=page_id,
            user_refs=user_refs,
            first_name=first_name,
            last_name=last_name,
            name=name,
            gender=gender,
            profile_pic=profile_pic,
            locale=locale,
            language=language,
            timezone=timezone,
            live_chat_url=live_chat_url,
            last_input_text=last_input_text,
            optin_phone=optin_phone,
            phone=phone,
            optin_email=optin_email,
            email=email,
            subscribed=subscribed,
            last_interaction=last_interaction,
            last_seen=last_seen,
            is_followup_enabled=is_followup_enabled,
            ig_username=ig_username,
            ig_id=ig_id,
            whatsapp_phone=whatsapp_phone,
            optin_whatsapp=optin_whatsapp,
            custom_fields=custom_fields,
            tags=tags,
        )

        subscriber.additional_properties = d
        return subscriber

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
