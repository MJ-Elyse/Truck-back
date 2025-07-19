from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.core.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import TokenError
from datetime import timedelta

from users.models import User

class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        
        user = User.get_user_by_email_and_password(email, password)

        if user is not None:
            refresh = RefreshToken.for_user(user)
            accessToken = str(refresh.access_token)
            refreshToken = str(refresh)

            response = Response({
                'accessToken': accessToken,
                'name': user.name
            })

            response.set_cookie(
                key="refreshToken",
                value=refreshToken,
                httponly=True,
                max_age=timedelta(days=30),  
                secure=False,
                samesite="None",
                path='/',
            )

            return response
        else:
            return Response({'detail': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        
class RefreshTokenHttpOnlyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get('refreshToken')
        if refresh_token is None:
            return Response({'detail': 'Refresh token is missing'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            refresh = RefreshToken(refresh_token)
            access_token = str(refresh.access_token)
            
            response = Response({'accessToken': access_token})
            response.set_cookie(
                key="refreshToken",
                value=refresh_token,
                max_age=timedelta(days=30),
                httponly=True,
                secure=False,
                samesite="None",
                path='/'
            )

            return response
        except TokenError:
            return Response({'detail': 'Invalid or expired refresh token'}, status=status.HTTP_401_UNAUTHORIZED)
        
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.COOKIES.get('refreshToken')

        try:
            refresh = RefreshToken(refresh_token)
            refresh.blacklist()
        
            response = Response({'detail': 'Successfully logged out'})
            response.delete_cookie('refreshToken')

            return response
        except TokenError:
            return Response({'detail': 'Invalid refresh token'}, status=status.HTTP_401_UNAUTHORIZED)

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        name = request.data.get('name')
        email = request.data.get('email')
        password = request.data.get('password')
        try:
            user = User.create_user(name, email, password)
            return Response({'message': 'User Created'}, status=status.HTTP_201_CREATED)
        
        except ValidationError as e:
            return Response({'Error': str(e)}, status=status.HTTP_400_BAD_REQUEST)