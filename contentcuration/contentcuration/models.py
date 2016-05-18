import logging
import os
from uuid import uuid4

from django.conf import settings
from django.contrib import admin
from django.core.files.storage import FileSystemStorage
from django.db import IntegrityError, connections, models
from django.db.utils import ConnectionDoesNotExist
from mptt.models import MPTTModel, TreeForeignKey
from django.utils.translation import ugettext as _
from kolibri.content.models import *
from constants import content_kinds, extensions, presets

class Channel(models.Model):
    """ Permissions come from association with organizations """
    channel_id = models.UUIDField(primary_key=False, unique=True, default=uuid4, editable=True)
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=400, blank=True)
    author = models.CharField(max_length=400, blank=True)
    editors = models.ManyToManyField(
        'auth.User',
        related_name='editable_channels',
        verbose_name=_("editors"),
        help_text=_("Users with edit rights"),
    )

    published = models.ForeignKey('TopicTree', null=True, blank=True, related_name='published')
    deleted =  models.ForeignKey('TopicTree', null=True, blank=True, related_name='deleted')
    clipboard =  models.ForeignKey('TopicTree', null=True, blank=True, related_name='clipboard')
    draft =  models.ForeignKey('TopicTree', null=True, blank=True, related_name='draft')
    bookmarked_by = models.ManyToManyField(
        'auth.User',
        related_name='bookmarked_channels',
        verbose_name=_("bookmarded by"),
    )

    class Meta:
        verbose_name = _("Channel")
        verbose_name_plural = _("Channels")

class TopicTree(models.Model):
    """Base model for all channels"""

    name = models.CharField(
        max_length=255,
        verbose_name=_("topic tree name"),
        help_text=_("Displayed to the user"),
    )
    channel = models.ForeignKey(
        'Channel',
        verbose_name=_("channel"),
        null=True,
        help_text=_("For different versions of the tree in the same channel (trash, edit, workspace)"),
    )
    root_node = models.ForeignKey(
        'ContentNode',
        verbose_name=_("root node"),
        null=True,
        help_text=_(
            "The starting point for the tree, the title of it is the "
            "title shown in the menu"
        ),
    )
    is_published = models.BooleanField(
        default=False,
        verbose_name=_("Published"),
        help_text=_("If published, students can access this channel"),
    )
    
    class Meta:
        verbose_name = _("Topic tree")
        verbose_name_plural = _("Topic trees")

class ContentTag(models.Model):
    tag_name = models.CharField(max_length=30, blank=True)
    tag_type = models.CharField(max_length=30, blank=True)
    
    def __str__(self):
        return self.tag_name

class ContentNode(MPTTModel, models.Model):
    """
    By default, all nodes have a title and can be used as a topic.
    """
    content_id = models.UUIDField(primary_key=False, default=uuid4, editable=False)
    title = models.CharField(max_length=200)
    description = models.CharField(max_length=400, blank=True)
    kind = models.ForeignKey('ContentKind', related_name='content_metadatas', blank=True, null=True)
    slug = models.CharField(max_length=100)
    total_file_size = models.IntegerField()
    license = models.ForeignKey('License')
    prerequisite = models.ManyToManyField('self', related_name='is_prerequisite_of', through='PrerequisiteContentRelationship', symmetrical=False, blank=True)
    is_related = models.ManyToManyField('self', related_name='relate_to', through='RelatedContentRelationship', symmetrical=False, blank=True)
    parent = TreeForeignKey('self', null=True, blank=True, related_name='children', db_index=True)
    tags = models.ManyToManyField(ContentTag, symmetrical=False, related_name='tagged_content', blank=True)
    sort_order = models.FloatField(max_length=50, default=0, verbose_name=_("sort order"), help_text=_("Ascending, lowest number shown first"))
    license_owner = models.CharField(max_length=200, blank=True, help_text=_("Organization of person who holds the essential rights"))

    created = models.DateTimeField(auto_now_add=True, verbose_name=_("created"))
    modified = models.DateTimeField(auto_now=True, verbose_name=_("modified"))

    published = models.BooleanField(
        default=False,
        verbose_name=_("Published"),
        help_text=_("If published, students can access this item"),
    )
    original_filename = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    @property
    def has_draft(self):
        return self.draft_set.all().exists()
    
    @property
    def get_draft(self):
        """
        NB! By contract, only one draft should always exist per node, this is
        enforced by the OneToOneField relation.
        :raises: Draft.DoesNotExist and Draft.MultipleObjectsReturned
        """
        return Draft.objects.get(publish_in=self)
    
    class MPTTMeta:
        order_insertion_by = ['sort_order']

    class Meta:
        verbose_name = _("Topic")
        verbose_name_plural = _("Topics")
        # Do not allow two nodes with the same name on the same level
        #unique_together = ('parent', 'title')

class ContentKind(models.Model):
    kind = models.CharField(primary_key=True, max_length=200, choices=content_kinds.choices)

    def __str__(self):
        return self.kind

class FileFormat(models.Model):
    extension = models.CharField(primary_key=True, max_length=40, choices=extensions.choices)

    def __str__(self):
        return self.extension

class FormatPreset(models.Model):
    id = models.CharField(primary_key=True, max_length=150, choices=presets.choices)
    readable_name = models.CharField(max_length=400)
    multi_language = models.BooleanField(default=False)
    supplementary = models.BooleanField(default=False)
    order = models.IntegerField()
    kind = models.ForeignKey(ContentKind, related_name='format_presets')
    allowed_formats = models.ManyToManyField(FileFormat, blank=True)

    def __str__(self):
        return self.name

class Language(models.Model):
    lang_code = models.CharField(primary_key=True, max_length=400)
    lang_name = models.CharField(max_length=400)

    def __str__(self):
        return self.lang_name

class File(models.Model):
    """
    The bottom layer of the contentDB schema, defines the basic building brick for content.
    Things it can represent are, for example, mp4, avi, mov, html, css, jpeg, pdf, mp3...
    """
    checksum = models.CharField(max_length=400, blank=True)
    available = models.BooleanField(default=False)
    file_size = models.IntegerField(blank=True, null=True)
    content_copy = models.FileField(upload_to=content_copy_name, storage=ContentCopyStorage(), max_length=500, blank=True)
    contentmetadata = models.ForeignKey(ContentNode, related_name='files', blank=True, null=True)
    file_format = models.ForeignKey(FileFormat, related_name='files', blank=True, null=True)
    preset = models.ForeignKey(FormatPreset, related_name='files', blank=True, null=True)
    lang = models.ForeignKey(Language, blank=True, null=True)

    class Admin:
        pass

    def __str__(self):
        return '{checksum}{extension}'.format(checksum=self.checksum, extension='.' + self.file_format.extension)

    def save(self, *args, **kwargs):
        """
        Overrider the default save method.
        If the content_copy FileField gets passed a content copy:
            1. generate the MD5 from the content copy
            2. fill the other fields accordingly
            3. update tracking for this content copy
        If None is passed to the content_copy FileField:
            1. delete the content copy.
            2. update tracking for this content copy
        """
        if self.content_copy:  # if content_copy is supplied, hash out the file
            md5 = hashlib.md5()
            for chunk in self.content_copy.chunks():
                md5.update(chunk)

            self.checksum = md5.hexdigest()
            self.available = True
            self.file_size = self.content_copy.size
            self.extension = os.path.splitext(self.content_copy.name)[1]
            # update ContentCopyTracking
            try:
                content_copy_track = ContentCopyTracking.objects.get(content_copy_id=self.checksum)
                content_copy_track.referenced_count += 1
                content_copy_track.save()
            except ContentCopyTracking.DoesNotExist:
                ContentCopyTracking.objects.create(referenced_count=1, content_copy_id=self.checksum)
        else:
            # update ContentCopyTracking, if referenced_count reach 0, delete the content copy on disk
            try:
                content_copy_track = ContentCopyTracking.objects.get(content_copy_id=self.checksum)
                content_copy_track.referenced_count -= 1
                content_copy_track.save()
                if content_copy_track.referenced_count == 0:
                    content_copy_path = os.path.join(settings.CONTENT_COPY_DIR, self.checksum[0:1], self.checksum[1:2], self.checksum + self.extension)
                    if os.path.isfile(content_copy_path):
                        os.remove(content_copy_path)
            except ContentCopyTracking.DoesNotExist:
                pass
            self.checksum = None
            self.available = False
            self.file_size = None
            self.extension = None
        super(File, self).save(*args, **kwargs)

class License(models.Model):
    """
    Normalize the license of ContentNode model
    """
    license_name = models.CharField(max_length=50)
    exists = models.BooleanField(
        default=False,
        verbose_name=_("license exists"),
        help_text=_("Tells whether or not a content item is licensed to share"),
    )

    def __str__(self):
        return self.license_name

class PrerequisiteContentRelationship(models.Model):
    """
    Predefine the prerequisite relationship between two ContentNode objects.
    """
    contentmetadata_1 = models.ForeignKey(ContentNode, related_name='%(app_label)s_%(class)s_1')
    contentmetadata_2 = models.ForeignKey(ContentNode, related_name='%(app_label)s_%(class)s_2')

    class Meta:
        unique_together = ['contentmetadata_1', 'contentmetadata_2']

    def clean(self, *args, **kwargs):
        # self reference exception
        if self.contentmetadata_1 == self.contentmetadata_2:
            raise IntegrityError('Cannot self reference as prerequisite.')
        # immediate cyclic exception
        elif PrerequisiteContentRelationship.objects.using(self._state.db)\
                .filter(contentmetadata_1=self.contentmetadata_2, contentmetadata_2=self.contentmetadata_1):
            raise IntegrityError(
                'Note: Prerequisite relationship is directional! %s and %s cannot be prerequisite of each other!'
                % (self.contentmetadata_1, self.contentmetadata_2))
        # distant cyclic exception
        # elif <this is a nice to have exception, may implement in the future when the priority raises.>
        #     raise Exception('Note: Prerequisite relationship is acyclic! %s and %s forms a closed loop!' % (self.contentmetadata_1, self.contentmetadata_2))
        super(PrerequisiteContentRelationship, self).clean(*args, **kwargs)

    def save(self, *args, **kwargs):
        self.full_clean()
        super(PrerequisiteContentRelationship, self).save(*args, **kwargs)


class RelatedContentRelationship(models.Model):
    """
    Predefine the related relationship between two ContentNode objects.
    """
    contentmetadata_1 = models.ForeignKey(ContentNode, related_name='%(app_label)s_%(class)s_1')
    contentmetadata_2 = models.ForeignKey(ContentNode, related_name='%(app_label)s_%(class)s_2')

    class Meta:
        unique_together = ['contentmetadata_1', 'contentmetadata_2']

    def save(self, *args, **kwargs):
        # self reference exception
        if self.contentmetadata_1 == self.contentmetadata_2:
            raise IntegrityError('Cannot self reference as related.')
        # handle immediate cyclic
        elif RelatedContentRelationship.objects.using(self._state.db)\
                .filter(contentmetadata_1=self.contentmetadata_2, contentmetadata_2=self.contentmetadata_1):
            return  # silently cancel the save
        super(RelatedContentRelationship, self).save(*args, **kwargs)

class Exercise(models.Model):

    title = models.CharField(
        max_length=50,
        verbose_name=_("title"),
        default=_("Title"),
        help_text=_("Title of the content item"),
    )

    description = models.TextField(
        max_length=200,
        verbose_name=_("description"),
        default=_("Description"),
        help_text=_("Brief description of what this content item is"),
    )


class AssessmentItem(models.Model):

    type = models.CharField(max_length=50, default="multiplechoice")
    question = models.TextField(blank=True)
    answers = models.TextField(default="[]")
    exercise = models.ForeignKey('Exercise', related_name="all_assessment_items")
