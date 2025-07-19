from django.db import models
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError

class User(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=21)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255, null=False, blank=False)

    def __str__(self):
        return self.name
    
    class Meta:
        db_table = 'users'

    @classmethod
    def get_user_by_email_and_password(cls, email, password):
        try:
            user = cls.objects.get(email=email)
            
            if check_password(password, user.password):
                return user
            else:
                return None
        except cls.DoesNotExist:
            return None
        
    @classmethod
    def create_user(cls, name, email, password):
        if cls.objects.filter(email=email).exists():
            raise ValidationError("Email already in use")
        
        hashed_password = make_password(password)
        
        try:
            user = cls.objects.create(name=name, email=email, password=hashed_password)
            return user
        except Exception as e:
            raise e