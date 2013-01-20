"""ModelAdmin for Contact"""
import StringIO
from django.conf import settings
from datetime import datetime

from django.contrib import admin
from django.dispatch import Signal
from django.conf.urls.defaults import url
from django.conf.urls.defaults import patterns
from django.core.urlresolvers import reverse
from django.shortcuts import render_to_response
from django.template import RequestContext
from django.utils.translation import ugettext_lazy as _
from django.http import HttpResponseRedirect
from django.contrib.admin.views.main import ChangeList
from django.db import DatabaseError

from emencia.django.newsletter.models import MailingList
from emencia.django.newsletter.settings import USE_WORKGROUPS
from emencia.django.newsletter.utils.importation import import_dispatcher
from emencia.django.newsletter.utils.workgroups import request_workgroups, \
                                                request_workgroups_contacts_pk
from emencia.django.newsletter.utils.vcard import \
        vcard_contacts_export_response
from emencia.django.newsletter.utils.excel import ExcelResponse


contacts_imported = Signal(providing_args=['source', 'type'])


class ContactAdmin(admin.ModelAdmin):
    date_hierarchy = 'creation_date'
    list_display = ('email', 'first_name', 'last_name', 'tester', 'subscriber',
                    'valid', 'total_subscriptions', 'creation_date')
    list_filter = ('subscriber', 'valid', 'tester',
                   'creation_date', 'modification_date')
    search_fields = ('email', 'first_name', 'last_name')
    fieldsets = (
        (None, {'fields': ('email', 'first_name', 'last_name')}),
        (_('Status'), {'fields': ('subscriber', 'valid', 'tester')}),
    )
    actions = ['create_mailinglist', 'export_vcard', 'export_excel']
    actions_on_top = False
    actions_on_bottom = True

    def queryset(self, request):
        queryset = super(ContactAdmin, self).queryset(request)
        if not request.user.is_superuser and USE_WORKGROUPS:
            contacts_pk = request_workgroups_contacts_pk(request)
            queryset = queryset.filter(pk__in=contacts_pk)
        return queryset

    def save_model(self, request, contact, form, change):
        workgroups = []
        if not contact.pk and not request.user.is_superuser \
               and USE_WORKGROUPS:
            workgroups = request_workgroups(request)
        contact.save()
        for workgroup in workgroups:
            workgroup.contacts.add(contact)

    def total_subscriptions(self, contact):
        """Display user subscriptions to unsubscriptions"""
        subscriptions = contact.subscriptions().count()
        unsubscriptions = contact.unsubscriptions().count()
        return '%s / %s' % (subscriptions - unsubscriptions, subscriptions)
    total_subscriptions.short_description = _('Total subscriptions')

    def export_vcard(self, request, queryset, export_name=''):
        """Export selected contact in VCard"""
        return vcard_contacts_export_response(queryset)
    export_vcard.short_description = _('Export contacts as VCard')

    def export_excel(self, request, queryset, export_name=''):
        """Export selected contact in Excel"""
        if not export_name:
            export_name = 'contacts_edn_%s' % \
                    datetime.now().strftime('%d-%m-%Y')
        return ExcelResponse(queryset, export_name)
    export_excel.short_description = _('Export contacts in Excel')

    def create_mailinglist(self, request, queryset):
        """Create a mailing list from selected contact"""
        when = str(datetime.now()).split('.')[0]
        new_mailing = MailingList(
            name=_('New mailinglist at %s') % when,
            description=_('New mailing list created in admin at %s') % when)
        new_mailing.save()

        if 'lite' in settings.DATABASES['default']['ENGINE']:
            self.message_user(
                request,
                _('SQLite3 or a SpatialLite database type detected, ' \
                  'please note you will be limited to 999 contacts ' \
                  'per mailing list.')
            )
        try:
            new_mailing.subscribers = queryset.all()
        except DatabaseError:
            new_mailing.subscribers = queryset.none()

        if not request.user.is_superuser and USE_WORKGROUPS:
            for workgroup in request_workgroups(request):
                workgroup.mailinglists.add(new_mailing)

        self.message_user(request, _('%s succesfully created.') % new_mailing)
        return HttpResponseRedirect(reverse(
            'admin:newsletter_mailinglist_change',
            args=[new_mailing.pk]
        ))
    create_mailinglist.short_description = _('Create a mailinglist')

    def importation(self, request):
        """Import contacts from a VCard"""
        opts = self.model._meta

        if request.POST:
            source = request.FILES.get('source') or \
                     StringIO.StringIO(request.POST.get('source', ''))
            if not request.user.is_superuser and USE_WORKGROUPS:
                workgroups = request_workgroups(request)
            else:
                workgroups = []
            inserted = import_dispatcher(source, request.POST['type'],
                                         workgroups)
            if inserted:
                contacts_imported.send(sender=self, source=source,
                                       type=request.POST['type'])

            self.message_user(
                request, _('%s contacts succesfully imported.') % inserted
            )

        context = {'title': _('Contact importation'),
                   'opts': opts,
                   'app_label': opts.app_label}

        return render_to_response('newsletter/contact_import.html',
                                  context, RequestContext(request))

    def filtered_request_queryset(self, request):
        """Return queryset filtered by the admin list view"""
        cl = ChangeList(request, self.model, self.list_display,
                        self.list_display_links, self.list_filter,
                        self.date_hierarchy, self.search_fields,
                        self.list_select_related, self.list_per_page,
                        self.list_editable, self)
        return cl.get_query_set()

    def creation_mailinglist(self, request):
        """Create a mailing list form the filtered contacts"""
        return self.create_mailinglist(request,
                                       self.filtered_request_queryset(request))

    def exportation_vcard(self, request):
        """Export filtered contacts in VCard"""
        return self.export_vcard(
            request, self.filtered_request_queryset(request),
            'contacts_edn_%s' % datetime.now().strftime('%d-%m-%Y')
        )

    def exportation_excel(self, request):
        """Export filtered contacts in Excel"""
        return self.export_excel(
            request, self.filtered_request_queryset(request),
            'contacts_edn_%s' % datetime.now().strftime('%d-%m-%Y')
        )

    def get_urls(self):
        urls = super(ContactAdmin, self).get_urls()
        my_urls = patterns(
            '',
            url(r'^import/$',
                self.admin_site.admin_view(self.importation),
                name='newsletter_contact_import'),
            url(r'^create_mailinglist/$',
                self.admin_site.admin_view(self.creation_mailinglist),
                name='newsletter_contact_create_mailinglist'),
            url(r'^export/vcard/$',
                self.admin_site.admin_view(self.exportation_vcard),
                name='newsletter_contact_export_vcard'),
            url(r'^export/excel/$',
                self.admin_site.admin_view(self.exportation_excel),
                name='newsletter_contact_export_excel'),
        )
        return my_urls + urls
